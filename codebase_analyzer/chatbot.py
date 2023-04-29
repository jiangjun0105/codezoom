# %%
import openai
from pathlib import Path
from yaml import safe_load
from revChatGPT.V1 import Chatbot


def get_access_token():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["access_token"]
    
def get_api_key():
    with open(Path("~/.openai/config.yaml").expanduser(), "r") as f:
        return safe_load(f)["api_key"]
    
openai.api_key = get_api_key()

chatgpt4_main = Chatbot(config={
  "access_token": get_access_token(),
  "model": "gpt-4"
})
chatgpt4_sub = Chatbot(config={
  "access_token": get_access_token(),
  "model": "gpt-4"
})
chatgpt3 = Chatbot(config={
  "access_token": get_access_token(),
  "parent_id": "64bc082d-7db8-419c-94c6-ed1766b6177e",
  "conversation_id": "df1f9013-06d0-40b9-970a-6b14e1d410bb",
})