import os
import json
import smtplib
import logging
import asyncio
import imaplib
from email import policy
from email.header import Header
from email.utils import formataddr
from email.parser import BytesParser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, filters
from openai import OpenAI

# Configure logging to file and console
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler('email_bot.log'),
                              logging.StreamHandler()])

# Variables for credentials
user_name = 'Your Name'
openai_api_key = ''
email_user = ''
email_password = ''
imap_url = 'mail.mail.net'
smtp_server = 'mail.mail.net'
smtp_port = int(465)
telegram_bot_token = ''
telegram_chat_id = ''
max_openai_char = int(8000) # max characters from an email body that can be send to OpenAI

# Initialize OpenAI Client
openai_client = OpenAI(api_key=openai_api_key)


async def schedule_email_checks(update: Update, context: CallbackContext) -> None:
    """Starts the job for checking emails periodically."""
    chat_id = update.effective_message.chat_id
    try:
        context.job_queue.run_repeating(
            callback=check_emails,
            interval=30,
            first=0,
            data={"chat_id": chat_id},  # Passed to the job through `data`
            name=str(chat_id)
        )
        await update.effective_message.reply_text('Email checking scheduled every 5 minutes.')
        logging.info(f"Scheduled email checking for chat_id: {chat_id}")
    except Exception as e:
        await update.effective_message.reply_text(f'Error scheduling email checks: {e}')
        logging.error(f"Error scheduling email checks for chat_id: {chat_id}: {e}")


async def check_emails(context: CallbackContext):
    """Check for new emails and notify the user via Telegram."""
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    logging.info(f"Checking emails for chat_id: {chat_id}")
    with imaplib.IMAP4_SSL(imap_url) as mail:
        mail.login(email_user, email_password)
        mail.select('inbox')
        _, email_ids = mail.search(None, '(UNSEEN)')
        if email_ids[0]:
            logging.info(f"New emails detected for chat_id: {chat_id}")
        else:
            logging.info(f"No new emails for chat_id: {chat_id}")
        for email_id in email_ids[0].split():
            _, data = mail.fetch(email_id, '(RFC822)')
            email_message = BytesParser(policy=policy.default).parsebytes(data[0][1])
            subject = email_message['subject']
            from_ = email_message['from']
            logging.info(f"PROCESSING EMAIL: {subject} FROM: {from_}")
            email_body = extract_email_body(email_message)
            truncated_email_body = truncate_email_content(email_body, max_openai_char)
            decision, action_suggestion, draft_reply = await draft_email_decision("Subject:" + subject + ", Body: " + truncated_email_body)

            if decision == "important":
                await prompt_for_action(context, chat_id, from_, subject, draft_reply, action_suggestion, email_id.decode('utf-8'), email_body)


def truncate_email_content(email_content, max_length=max_openai_char):
    """Truncates the email content to a maximum length, preserving whole words.
    Returns an empty string if email_content is None."""
    if email_content is None:
        logging.error("truncate_email_content received None as email_content.")
        return "Email content could not be retrieved."

    if len(email_content) <= max_length:
        logging.info("Email content within acceptable length, no truncation needed.")
        return email_content

    # Find the last whitespace character before the max_length to avoid cutting in the middle of a word.
    idx = email_content.rfind(' ', 0, max_length)
    # If no whitespace is found, hard truncate
    if idx == -1:
        logging.warning("Whitespace not found for truncation, performing hard truncate.")
        return email_content[:max_length] + " [...]"
    # Otherwise, truncate at the last found whitespace to preserve whole words.
    logging.info("Email content truncated to fit maximum length.")
    return email_content[:idx] + " [...]"


def extract_content_from_part(part):
    """Extracts content from a single part of an email."""
    content_type = part.get_content_type()
    charset = part.get_content_charset('utf-8')  # Default to UTF-8 if charset is not specified

    if content_type == "text/plain" or content_type == "text/html":
        content = part.get_payload(decode=True).decode(charset, errors="ignore")
        logging.info(f"Content extracted from part with content_type: {content_type}")
        return content
    logging.info(f"No content extracted: part content_type was {content_type}, not 'text/plain' or 'text/html'.")
    return None


def extract_email_body(email_message):
    """Extract the plain text email body, prioritizing plain text over HTML content."""
    text_content = None  # Store plain text content
    html_content = None  # Store HTML content, used as a fallback

    def _walk_parts(part):
        nonlocal text_content, html_content

        if text_content and html_content:
            # If we have both plain and HTML content, no need to explore further
            return

        if part.is_multipart():
            # Iterate over each part of a multipart email
            for subpart in part.get_payload():
                _walk_parts(subpart)
        else:
            # If part is non-multipart
            content_type = part.get_content_type()
            charset = part.get_content_charset('utf-8')  # UTF-8 as a safe default

            content = part.get_payload(decode=True)
            if content:
                content = content.decode(charset, errors='replace')

            if content_type == 'text/plain' and not text_content:
                text_content = content
                logging.info("Plain text content extracted.")
            elif content_type == 'text/html' and not html_content:
                html_content = content
                logging.info("HTML content extracted as fallback.")

    # Start the recursive walk from the top-level email message
    _walk_parts(email_message)

    # Log the outcome of the extraction process
    if text_content is not None:
        logging.info("Returning plain text email content.")
        return text_content
    elif html_content is not None:
        logging.warning("Falling back to returning HTML email content.")
        return html_content
    logging.error("No email content could be extracted.")
    return ""


async def draft_email_decision(email_body: str):
    logging.info("Drafting email decision based on email body.")
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: openai_client.chat.completions.create(
                model="gpt-3.5-turbo-0125",
                messages=[
                    {"role": "system", "content": f"You're Eddie, a helpful assistant designed to output JSON. Assess the email and suggest an appropriate action. Response JSON must contain: 'decision', 'action', 'draft_reply'. 'decision' should be 'important' or 'not important'. Emails are important if they need to be seen by the user or they need a reply. 'action' should be the suggestion to the user on how to proceed. 'draft_reply' is a suggested reply for this email. 'draft_reply' can be the text 'none'. Emails are only important if they are directed explicitly to me, {user_name}, and are not mass mailers or spam. I am not interested in advertisements. Emails can contain basic HTML as long as it does not break the JSON block. If the email contains a link, you can send the link with the action message as long as any tracking parameters are removed."},
                    {"role": "user", "content": email_body}
                ],
                response_format={"type": "json_object"}
            )
        )
        content = json.loads(response.choices[0].message.content)
        logging.info("Successfully received decision from OpenAI.")
        return content.get("decision"), content.get("action"), content.get("draft_reply")
    except Exception as e:
        logging.error(f"Error in drafting email decision: {e}")
        raise


async def generate_new_draft_with_revision(original_email_body: str, revision_request: str):
    logging.info("Generating new draft with revision.")
    try:
        combined_request = f"{original_email_body}\nRevision needed: {revision_request}"
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: openai_client.chat.completions.create(
                model="gpt-3.5-turbo-0125",
                messages=[
                    {"role": "system", "content": "You're a helpful assistant designed to output JSON. Draft a new reply based on the revision request. Response JSON must contain the 'draft_reply' field containing the new reply."},
                    {"role": "user", "content": combined_request}
                ],
                response_format={"type": "json_object"}
            )
        )
        content = json.loads(response.choices[0].message.content)
        logging.info("Successfully generated new draft with revision from OpenAI.")
        return content.get("draft_reply"), "important", "Revision"
    except Exception as e:
        logging.error(f"Error in generating new draft with revision: {e}")
        raise


async def receive_revision_request(update: Update, context: CallbackContext) -> None:
    logging.info("Receiving revision request.")
    if 'awaiting_revision_for' in context.user_data:
        email_id = context.user_data['awaiting_revision_for']
        revision_request = update.message.text
        email_data = context.bot_data.get(email_id, {})

        # Check if 'email_body' exists in email_data before proceeding
        if 'email_body' not in email_data:
            logging.error("Original email body not found for revision.")
            await update.message.reply_text("Sorry, I couldn't find the original email body for the revision.")
            return

        original_email_body = email_data['email_body']
        truncated_email_body = truncate_email_content(original_email_body, max_openai_char)
        new_draft_reply, decision, action_suggestion = await generate_new_draft_with_revision(truncated_email_body, revision_request)

        del context.user_data['awaiting_revision_for']

        context.bot_data[email_id] = {**email_data, 'draft_reply': new_draft_reply}

        await prompt_for_action(context, update.effective_chat.id, email_data.get('from_address', ''), email_data.get('subject', ''), new_draft_reply, action_suggestion, email_id, email_data.get('email_body', ''))
        logging.info("Revision request processed successfully.")
    else:
        logging.info("No revision request awaiting; ignored message.")
        await update.message.reply_text("You're currently not awaiting any revision requests.")


async def prompt_for_action(context: CallbackContext, chat_id: str, from_address: str, subject: str, draft_reply: str, action_suggestion: str, email_id: str, email_body: str):
    logging.info(f"Prompting for action on email from {from_address} with subject '{subject}'.")
    try:
        keyboard = [
            [InlineKeyboardButton("Approve Reply", callback_data=f"approve:{email_id}"),
             InlineKeyboardButton("Dismiss", callback_data=f"dismiss:{email_id}")],
            [InlineKeyboardButton("Request Revision", callback_data=f"revise:{email_id}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message_text = f"From: {from_address}\nSubject: {subject}\n\nSuggested Action: {action_suggestion}\n\nDraft reply:\n{draft_reply}"
        await context.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            reply_markup=reply_markup
        )

        # Store needed email data in context.bot_data for later usage
        context.bot_data[email_id] = {"from_address": from_address, "subject": subject, "draft_reply": draft_reply, "email_body": email_body}
        logging.info(f"Action prompted successfully for email '{subject}', waiting for user response.")
    except Exception as e:
        logging.error(f"Failed to prompt for action on email '{subject}': {e}")
        raise


async def send_email_reply(to_address: str, subject: str, body: str, html_format: bool):
    logging.info(f"Preparing to send email reply to '{to_address}' with subject 'Re: {subject}'.")
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send_email_sync, to_address, subject, body, html_format)
        logging.info(f"Email sent successfully to '{to_address}'.")
    except Exception as e:
        logging.error(f"Failed to send email to '{to_address}': {e}")
        raise


def _send_email_sync(to_address: str, subject: str, body: str, html_format: bool = True):
    """Synchronous helper function to send an email."""
    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as smtp:
            smtp.login(email_user, email_password)

            sender_name = user_name
            formatted_from = formataddr((str(Header(sender_name, 'utf-8')), email_user))

            if html_format:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = f"Re: {subject}"
                msg['From'] = formatted_from
                msg['To'] = to_address

                html_content = body + "<br><br><p>PS: This email was written by my automated AI secretary. Apologies for any weirdness.</p>"
                part = MIMEText(html_content, 'html')
                msg.attach(part)
            else:
                plain_content = body + "\n\nPS: This email was written by my automated AI secretary. Apologies for any weirdness."
                msg = MIMEText(plain_content, 'plain')
                msg['Subject'] = f"Re: {subject}"
                msg['From'] = formatted_from
                msg['To'] = to_address

            smtp.sendmail(email_user, to_address, msg.as_string())
            logging.info(f"Email successfully sent to '{to_address}'.")
    except Exception as e:
        logging.error(f"Error sending email to '{to_address}': {e}")
        raise


async def handle_action(update: Update, context: CallbackContext) -> None:
    logging.info("Handling action from Telegram callback query.")
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query first
    action, email_id = query.data.split(':')
    email_data = context.bot_data.get(email_id, {})

    if not email_data:
        logging.error(f"No email data found for email_id {email_id}.")
        await query.edit_message_text(text="An error occurred: email data not found.")
        return

    subject = email_data.get('subject', 'Email')

    try:
        if action == "approve":
            to_address = email_data.get('from_address')
            body = email_data.get('draft_reply', '')
            await send_email_reply(to_address, subject, body, html_format=True)
            await query.edit_message_text(text=f"Reply to '{subject}' sent.")
            logging.info(f"Reply sent for email '{subject}' to '{to_address}'.")
        elif action == "dismiss":
            await query.edit_message_text(text=f"'{subject}' dismissed.")
            logging.info(f"Email '{subject}' dismissed.")
        elif action == "revise":
            prompt_text = "Please send your detailed revision request. Type it out and send."
            context.user_data['awaiting_revision_for'] = email_id
            await query.message.reply_text(text=prompt_text)
            logging.info(f"Requested revision for email '{subject}'. Prompting user for details.")
    except Exception as e:
        logging.error(f"Error handling action '{action}' for email '{subject}': {e}")
        await query.edit_message_text(text="An error occurred while processing your request.")


def main() -> None:
    application = Application.builder().token(telegram_bot_token).build()
    application.add_handler(CommandHandler("start", schedule_email_checks))
    application.add_handler(CallbackQueryHandler(handle_action, pattern="^(approve|dismiss|revise):[0-9]+"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_revision_request))
    application.run_polling()
    logging.info("Email bot started successfully.")

if __name__ == '__main__':
    main()
