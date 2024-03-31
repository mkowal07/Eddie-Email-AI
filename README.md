# Eddie-Email-AI
Eddie is a Python program that helps manage your email inbox. It monitors an inbox for new unread email, decides if an email needs user attention, and if so will notify the user of the email via Telegram and suggest a reply, which can then be revised. If the user chooses to send the drafted reply, Eddie will send the email. 

Eddie presents three options for incoming email deemed worthy of attention: 

- **Approve Reply** - sends the AI drafted reply as-is
- **Dismiss** - Does nothing, removes notification, email is marked as read
- **Request Revision** - Asks the user for suggestions for a new draft, writes the new draft, and sends it to the user for approval again.

Emails that are deemed not worthy of the user's attention are simply marked as read. 


![eddie1](https://github.com/mkowal07/Eddie-Email-AI/assets/18445565/f77dae75-4b72-483f-8554-fdb289712b89) ![eddie2](https://github.com/mkowal07/Eddie-Email-AI/assets/18445565/478e3694-0533-4e34-bca6-37ef5b2d8293)![eddie3](https://github.com/mkowal07/Eddie-Email-AI/assets/18445565/02e5f217-cf8a-4833-925d-d4712710c62d)





## Requirements
- **OpenAI Chat Completions API** - Works with either gpt-4-turbo-preview or gpt-3.5-turbo-0125 models. JSON mode is used https://platform.openai.com/docs/guides/text-generation/json-mode extensively. 
- **Telegram Bot** - Uses a Telegram bot to communicate with the user. Why Telegram? It's free, I already knew the API, and it has what is needed for this purpose. See https://core.telegram.org/bots/tutorial for creating a bot.
- Send the ```/start```  message to the bot to start email monitoring once everything is setup.
- A place to run the Python script continously - I've tested this on Debian and Arch with Python 3.11.
- Pip packages -
  ```pip install "python-telegram-bot[job-queue]" openai```

```
annotated-types==0.6.0
anyio==4.3.0
APScheduler==3.10.4
certifi==2024.2.2
distro==1.9.0
h11==0.14.0
httpcore==1.0.5
httpx==0.27.0
idna==3.6
openai==1.14.3
pydantic==2.6.4
pydantic_core==2.16.3
python-telegram-bot==21.0.1
pytz==2024.1
six==1.16.0
sniffio==1.3.1
tqdm==4.66.2
typing_extensions==4.10.0
tzlocal==5.2
```
