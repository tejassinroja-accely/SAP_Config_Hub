from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel
import os
from dotenv import load_dotenv
load_dotenv()

llm = AzureChatOpenAI(model="gpt-4.1")

class Settings(BaseModel):
    company_id: str
    username: str
    password: str

settings = Settings(
    company_id=os.getenv("company_id"),
    username=os.getenv("username"),
    password=os.getenv("password")
)