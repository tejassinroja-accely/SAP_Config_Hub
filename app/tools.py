from app.sap_config_hub import SapConfigHub
from langchain_core.tools import tool
from app.config import llm, settings
from langfuse.langchain import CallbackHandler
from dotenv import load_dotenv
load_dotenv()

callback = CallbackHandler()
config = SapConfigHub(company_id=settings.company_id, username=settings.username, password=settings.password)

@tool
async def go_to_url_tool(url: str, new_tab: bool):
     """
      Navigate to URL, set new_tab=True to open in new tab, False to navigate in current tab
     """
    # wrapper calls bound method on the singleton agent
     return await config.go_to_url(url, new_tab)

@tool
async def current_page_index():
     """
        Use this fucntion to get the interactive element index
     """
     return await config.current_page_index()
@tool
async def wait(seconds: int):
     """
     Wait for x seconds (default 3) (max 30 seconds). This can be used to wait until the page is fully loaded.
     """
     return await config.wait(seconds=seconds)

@tool
async def click_element_by_index(index: int, while_holding_ctrl: bool = False):
     """
        'Click element by index. Only indices from your browser_state are allowed. Never use an index that is not inside your current browser_state. Set while_holding_ctrl=True to open any resulting navigation in a new tab.'
     """
     return await config.click_element_by_index(index=index,while_holding_ctrl=while_holding_ctrl)

@tool
async def input_text(index: int, text: str, clear_existing: bool, has_sensitive_data: bool = False, sensitive_data: dict[str, str | dict[str, str]] | None = None):
     'Input text into an input interactive element. Only input text into indices that are inside your current browser_state. Never input text into indices that are not inside your current browser_state.'
        
     return await config.input_text(index=index,text=text, clear_existing=clear_existing,has_sensitive_data=has_sensitive_data,sensitive_data=sensitive_data)

@tool
async def scroll(down: bool, num_pages: float, frame_element_index: int | None = None):
        """Scroll the page by specified number of pages (set down=True to scroll down, down=False to scroll up, num_pages=number of pages to scroll like 0.5 for half page, 10.0 for ten pages, etc.). 
        Default behavior is to scroll the entire page. This is enough for most cases.
        Optional if there are multiple scroll containers, use frame_element_index parameter with an element inside the container you want to scroll in. For that you must use indices that exist in your browser_state (works well for dropdowns and custom UI components). 
        Instead of scrolling step after step, use a high number of pages at once like 10 to get to the bottom of the page.
        If you know where you want to scroll to, use scroll_to_text instead of this tool.
        
        Note: For multiple pages (>=1.0), scrolls are performed one page at a time to ensure reliability. Page height is detected from viewport, fallback is 1000px per page.
        """
        return await config.scroll(down, num_pages, frame_element_index)

@tool
async def send_keys(self, keys: str):
      'Send strings of special keys to use e.g. Escape, Backspace, Insert, PageDown, Delete, Enter, or Shortcuts such as `Control+o`, `Control+Shift+T`'
      return await config.send_keys(keys)

@tool
async def get_dropdown_options(self,index: int):
        """
        Get all options from a native dropdown or ARIA menu
        """
        return await config.get_dropdown_options(index)


async def login():
    "This tool log in and redirect to home page"
    return await config.login_script()


async def deep_agent():
        from deepagents import create_deep_agent

        # tools = config.tools_list()
        agent = create_deep_agent(
        tools=[go_to_url_tool, wait, current_page_index,click_element_by_index, input_text, scroll, send_keys, get_dropdown_options],
        instructions="""You are the browser agent based on user query you will interact with the current browser with available tools each tool is designed to handle something on the browser page
        You have a list of tools:
        go_to_url_tool : navigate through the particular url
        current_page_index: gives the indexed dom element of the current page
        wait : utilize for waiting till page loads
        click_element_by_index : use the current page dom element to find the index and use the tool to click
        input_txt : use the current page dom element to find the appropriate place to input text with index
        scroll: you can scroll the current page with this tool
        send_keys: Send strings of special keys to use e.g. Escape, Backspace, Insert, PageDown, Delete, Enter, or Shortcuts such as
        get_dropdown_option: Get all options from a native dropdown or ARIA menu
        """,
        model=llm
    )
        return agent
async def run_deep_agent():
        agent = await deep_agent()
        browser_session = await config.get_browser_session()
        await browser_session.start()
        async for stream_mode, chunk in agent.astream({"messages": [{"role": "user", "content": f'Go to https://salesdemo.successfactors.eu/ use {settings.company_id} then continue then type username {settings.username} then type password {settings.password} then double click the continue then landed on home page then open home drop down and click admin centre you have done your work'}]}, stream_mode=["updates", "messages", "custom"], config={"recursion_limit": 1000, "callbacks":[callback]}):
              print(stream_mode,":")
              print(chunk)
        
        # await browser_session.kill()
        return None
import asyncio 

asyncio.run(run_deep_agent())