# browser_use
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.tools.views import (
	ClickElementAction,
	CloseTabAction,
	DoneAction,
	GetDropdownOptionsAction,
	GoToUrlAction,
	InputTextAction,
	NoParamsAction,
	ScrollAction,
	SearchAction,
	SelectDropdownOptionAction,
	SendKeysAction,
	StructuredOutputAction,
	SwitchTabAction,
	UploadFileAction,
)
from browser_use.tools.service import _detect_sensitive_key_name
from browser_use.browser.views import BrowserError
from browser_use.browser import BrowserSession
from browser_use.browser.events import (
	ClickElementEvent,
	CloseTabEvent,
	GetDropdownOptionsEvent,
	GoBackEvent,
	NavigateToUrlEvent,
	ScrollEvent,
	ScrollToTextEvent,
	SendKeysEvent,
	SwitchTabEvent,
	TypeTextEvent,
	UploadFileEvent,
    ScreenshotEvent
)
from browser_use.browser.profile import BrowserProfile

# app
from app.config import setup_logger
from app.config import settings
from app.config import llm

# langchain
from langchain_core.tools import tool
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage

# langgraph
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import Command

# utility
from typing import Optional, TypedDict, NotRequired, Annotated, Literal
from deepagents.tools import write_todos, WRITE_TODOS_DESCRIPTION, Todo
import asyncio


logger = setup_logger("SAP_Config_Hub")



class AgentState(TypedDict):
    todos: NotRequired[list[Todo]]
    messages: Annotated[list[BaseMessage],add_messages]
    current_state: str

class TaskExecutor(TypedDict):
    current_task: str
    last_task: str
    message: BaseMessage
    current_state: str


class SapConfigHub:
    def __init__(self,company_id,username,password):
        self._SAP_Company_Id = company_id
        self._sap_username = username
        self._sap_password = password
        self._browser_session: Optional[BrowserSession] = None
        self.browser_state_summary = None
        self.tool_node = ToolNode(self.tools_list())

    async def login_script(self):
        """
        Robust login script:
        - starts browser
        - navigates (using go_to_url wrapper)
        - waits and verifies elements exist
        - inputs company id, username, password (with clear_existing)
        - clicks appropriate buttons (while_holding_ctrl False)
        Returns a string describing the final status or error.
        """
        try:
            # ensure browser session exists and started
            browser_session = await self.get_browser_session()
            await browser_session.start()

            # Use your go_to_url wrapper so you get the same error handling / logs
            nav_msg = await self.go_to_url(url="https://salesdemo.successfactors.eu/", new_tab=False)
            # go_to_url returns (msg, memory) on success or error string on failure
            if isinstance(nav_msg, str) and nav_msg.startswith("Navigation failed"):
                return f"Navigation failed: {nav_msg}"
            # if it's a tuple like (msg,memory) keep going

            # small wait for page to settle; consider one of your wait helpers
            await self.wait(2)

            # sanity-check: make sure required indices exist before acting
            # Replace these indices with correct ones you discovered with current_page_index()
            company_index = 1
            username_index = 1   # update if different
            password_index = 2   # update if different
            continue_button_index = 10
            intermediate_button_index = 4  # if you need to click something before username/password

            # helper to assert element presence and return node if you want
            node = await browser_session.get_element_by_index(company_index)
            if node is None:
                # give user actionable guidance
                return ("Company ID input (index=%d) not found. "
                        "Call current_page_index() to inspect available indices.") % company_index

            # Input company id (pass clear_existing)
            result = await self.input_text(company_index, text=self._SAP_Company_Id, clear_existing=True)
            # input_text returns (msg, metadata) on success or error object/string on failure
            if isinstance(result, str) and result.startswith("Failed"):
                return f"Input company id failed: {result}"

            await self.wait(1)

            # Click the next element (pass while_holding_ctrl explicitly)
            click_res = await self.click_element_by_index(intermediate_button_index, while_holding_ctrl=False)
            if isinstance(click_res, str) and click_res.startswith("Failed"):
                # try to continue anyway or return early
                return f"Click failed (index {intermediate_button_index}): {click_res}"

            await self.wait(1)

            # Input username & password
            username_res = await self.input_text(username_index, text=self._sap_username, clear_existing=True)
            if isinstance(username_res, str) and username_res.startswith("Failed"):
                return f"Input username failed: {username_res}"

            await self.wait(0.5)

            password_res = await self.input_text(password_index, text=self._sap_password, clear_existing=True, has_sensitive_data=True, sensitive_data={"password": self._sap_password})
            if isinstance(password_res, str) and password_res.startswith("Failed"):
                return f"Input password failed: {password_res}"

            await self.wait(0.5)

            # Click continue (explicit boolean)
            final_click = await self.click_element_by_index(continue_button_index, while_holding_ctrl=False)
            if isinstance(final_click, str) and final_click.startswith("Failed"):
                return f"Final click failed: {final_click}"

            await self.wait(2)

            # Optionally confirm that login succeeded by checking for a known post-login element or URL
            browser_state = await browser_session.get_browser_state_summary(include_screenshot=False)
            # Quick heuristic: check if URL changed or DOM includes something expected
            current_url = getattr(browser_session, "current_url", None)
            # return success message
            return "Login sequence executed — check browser to confirm; browser_state_summary captured."

        except Exception as e:
            # return the actual exception text (caller can print it)
            return f"Something went wrong with error: {type(e).__name__}: {e}"
        

    async def get_browser_session(self) -> BrowserSession:
        if self._browser_session is None:
            self._browser_session = BrowserSession(browser_profile=BrowserProfile(minimum_wait_page_load_time=3))
        return self._browser_session

    async def get_llm_with_tools(self, tools):
         llm_with_tool = llm.bind_tools(tools)
         return llm_with_tool
    
    async def current_page_index(self):
        """
        Use this fucntion to get the interactive element index
        """
        session = await self.get_browser_session()
        browser_state_summary = await session.get_browser_state_summary(include_screenshot = False)
        self.browser_state_summary = browser_state_summary
        if not browser_state_summary or not browser_state_summary.dom_state or not browser_state_summary.dom_state._root:
            print("Error: Could not get DOM snapshot or root node is None.")
            return

        # The DOMTreeSerializer expects an EnhancedDOMTreeNode as its root_node
        # We can get this from the SimplifiedNode's original_node attribute
        enhanced_dom_tree_root = browser_state_summary.dom_state._root.original_node

        # Instantiate DOMTreeSerializer
        # paint_order_filtering is True by default, so PaintOrderRemover will be used
        serializer = DOMTreeSerializer(root_node=enhanced_dom_tree_root)

        # Serialize accessible elements
        serialized_dom_state, timing_info = serializer.serialize_accessible_elements()

        # Get the final textual output for LLM
        final_index_tree = DOMTreeSerializer.serialize_tree(
            node=serialized_dom_state._root,
            include_attributes=['id', 'name', 'aria-label', 'role', 'placeholder', 'value', 'type', 'title', 'alt', 'label']
        )
        return final_index_tree

        # **Tools**

    # @tool
    async def go_to_url(self, url:str, new_tab: bool):
                """
                'Navigate to URL, set new_tab=True to open in new tab, False to navigate in current tab'
                """
                try:
                    # Dispatch navigation event
                    browser_session = await self.get_browser_session()
                    await browser_session.start()
                    event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=url, new_tab=new_tab))
                    await event
                    await event.event_result(raise_if_any=True, raise_if_none=False)

                    if new_tab:
                        memory = f'Opened new tab with URL {url}'
                        msg = f'🔗  Opened new tab with url {url}'
                    else:
                        memory = f'Navigated to {url}'
                        msg = f'🔗 {memory}'

                    logger.info(msg)
                    return msg, memory
                except Exception as e:
                    error_msg = str(e)
                    # Always log the actual error first for debugging
                    browser_session.logger.error(f'❌ Navigation failed: {error_msg}')

                    # Check if it's specifically a RuntimeError about CDP client
                    if isinstance(e, RuntimeError) and 'CDP client not initialized' in error_msg:
                        browser_session.logger.error('❌ Browser connection failed - CDP client not properly initialized')
                        return f'Browser connection error: {error_msg}'
                    # Check for network-related errors
                    elif any(
                        err in error_msg
                        for err in [
                            'ERR_NAME_NOT_RESOLVED',
                            'ERR_INTERNET_DISCONNECTED',
                            'ERR_CONNECTION_REFUSED',
                            'ERR_TIMED_OUT',
                            'net::',
                        ]
                    ):
                        site_unavailable_msg = f'Navigation failed - site unavailable: {url}'
                        browser_session.logger.warning(f'⚠️ {site_unavailable_msg} - {error_msg}')
                        return site_unavailable_msg
                    else:
                        # Return error in ActionResult instead of re-raising
                        return f'Navigation failed: {str(e)}'
    
    async def wait(self,seconds: int = 2):
            """
            'Wait for x seconds (default 2) (max 30 seconds). This can be used to wait until the page is fully loaded.'
            """
            actual_seconds = min(max(seconds, 0), 30)
            memory = f'Waited for {seconds} seconds'
            logger.info(f'🕒 waited for {actual_seconds}')
            await asyncio.sleep(actual_seconds)
            return memory
    
    async def click_element_by_index(self,index: int , while_holding_ctrl: bool):
                """
                'Click element by index. Only indices from your browser_state are allowed. Never use an index that is not inside your current browser_state. Set while_holding_ctrl=True to open any resulting navigation in a new tab.'
                """
                # Dispatch click event with node
                try:
                    assert index != 0, (
                        'Cannot click on element with index 0. If there are no interactive elements use scroll(), wait(), refresh(), etc. to troubleshoot'
                    )
                    browser_session = await self.get_browser_session()
                    # Look up the node from the selector map
                    node = await browser_session.get_element_by_index(index)
                    if node is None:
                        raise ValueError(f'Element index {index} not found in browser state')

                    event = browser_session.event_bus.dispatch(
                        ClickElementEvent(node=node, while_holding_ctrl=while_holding_ctrl or False)
                    )
                    await event
                    # Wait for handler to complete and get any exception or metadata
                    click_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)
                    memory = 'Clicked element'

                    if while_holding_ctrl:
                        memory += ' and opened in new tab'

                    # Check if a new tab was opened (from watchdog metadata)
                    elif isinstance(click_metadata, dict) and click_metadata.get('new_tab_opened'):
                        memory += ' - which opened a new tab'

                    msg = f'🖱️ {memory}'
                    logger.info(msg)

                    # Include click coordinates in metadata if available
                    return memory,click_metadata if isinstance(click_metadata, dict) else None
                    
                except BrowserError as e:
                    if 'Cannot click on <select> elements.' in str(e):
                        try:
                            return await self.get_dropdown_options(
                                params=GetDropdownOptionsAction(index=index), browser_session=browser_session
                            )
                        except Exception as dropdown_error:
                            logger.error(
                                f'Failed to get dropdown options as shortcut during click_element_by_index on dropdown: {type(dropdown_error).__name__}: {dropdown_error}'
                            )
                        return 'Can not click on select elements.'

                    return e
                except Exception as e:
                    error_msg = f'Failed to click element {index}: {str(e)}'
                    return error_msg
    
    async def get_dropdown_options(self,index: int):
                """
                Get all options from a native dropdown or ARIA menu
                """
                # Look up the node from the selector map
                browser_session = await self.get_browser_session()
                node = await browser_session.get_element_by_index(index)
                if node is None:
                    raise ValueError(f'Element index {index} not found in browser state')

                # Dispatch GetDropdownOptionsEvent to the event handler

                event = browser_session.event_bus.dispatch(GetDropdownOptionsEvent(node=node))
                dropdown_data = await event.event_result( raise_if_none=True, raise_if_any=True)

                if not dropdown_data:
                    raise ValueError('Failed to get dropdown options - no data returned')

                # Use structured memory from the handler
                return dropdown_data
    
    async def input_text(self,
        index : int,
        text : str,
        clear_existing: bool,
        has_sensitive_data: bool = False,
        sensitive_data: dict[str, str | dict[str, str]] | None = None,
        browser_session: BrowserSession = None
    ):
        'Input text into an input interactive element. Only input text into indices that are inside your current browser_state. Never input text into indices that are not inside your current browser_state.'
        # Look up the node from the selector map
        browser_session = await self.get_browser_session()
        # params = InputTextAction(index=index, text=text, clear_existing=clear_existing)
        node = await browser_session.get_element_by_index(index)
        if node is None:
            raise ValueError(f'Element index {index} not found in browser state')

        # Dispatch type text event with node
        try:
            # Detect which sensitive key is being used
            sensitive_key_name = None
            if has_sensitive_data and sensitive_data:
                sensitive_key_name = _detect_sensitive_key_name(text, sensitive_data)

            event = browser_session.event_bus.dispatch(
                TypeTextEvent(
                    node=node,
                    text=text,
                    clear_existing=clear_existing,
                    is_sensitive=has_sensitive_data,
                    sensitive_key_name=sensitive_key_name,
                )
            )
            await event
            input_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)

            # Create message with sensitive data handling
            if has_sensitive_data:
                if sensitive_key_name:
                    msg = f'Input {sensitive_key_name} into element {index}.'
                    log_msg = f'Input <{sensitive_key_name}> into element {index}.'
                else:
                    msg = f'Input sensitive data into element {index}.'
                    log_msg = f'Input <sensitive> into element {index}.'
            else:
                msg = f"Input '{text}' into element {index}."
                log_msg = msg

            logger.debug(log_msg)

            # Include input coordinates in metadata if available
            return msg, input_metadata if isinstance(input_metadata, dict) else None
        except BrowserError as e:
            return e
        except Exception as e:
            # Log the full error for debugging
            logger.error(f'Failed to dispatch TypeTextEvent: {type(e).__name__}: {e}')
            error_msg = f'Failed to input text into element {index}: {e}'
            return error_msg
        
    async def scroll(self, down: bool, num_pages: float,frame_element_index: int | None = None):
                """Scroll the page by specified number of pages (set down=True to scroll down, down=False to scroll up, num_pages=number of pages to scroll like 0.5 for half page, 10.0 for ten pages, etc.). 
			Default behavior is to scroll the entire page. This is enough for most cases.
			Optional if there are multiple scroll containers, use frame_element_index parameter with an element inside the container you want to scroll in. For that you must use indices that exist in your browser_state (works well for dropdowns and custom UI components). 
			Instead of scrolling step after step, use a high number of pages at once like 10 to get to the bottom of the page.
			If you know where you want to scroll to, use scroll_to_text instead of this tool.
			
			Note: For multiple pages (>=1.0), scrolls are performed one page at a time to ensure reliability. Page height is detected from viewport, fallback is 1000px per page.
			"""
                browser_session = await self.get_browser_session()
                try:
                    # Look up the node from the selector map if index is provided
                    # Special case: index 0 means scroll the whole page (root/body element)
                    node = None
                    if frame_element_index is not None and frame_element_index != 0:
                        node = await browser_session.get_element_by_index(frame_element_index)
                        if node is None:
                            # Element does not exist
                            msg = f'Element index {frame_element_index} not found in browser state'
                            return msg

                    direction = 'down' if down else 'up'
                    target = (
                        'the page'
                        if frame_element_index is None or frame_element_index == 0
                        else f'element {frame_element_index}'
                    )

                    # Get actual viewport height for more accurate scrolling
                    try:
                        cdp_session = await browser_session.get_or_create_cdp_session()
                        metrics = await cdp_session.cdp_client.send.Page.getLayoutMetrics(session_id=cdp_session.session_id)

                        # Use cssVisualViewport for the most accurate representation
                        css_viewport = metrics.get('cssVisualViewport', {})
                        css_layout_viewport = metrics.get('cssLayoutViewport', {})

                        # Get viewport height, prioritizing cssVisualViewport
                        viewport_height = int(css_viewport.get('clientHeight') or css_layout_viewport.get('clientHeight', 1000))

                        logger.debug(f'Detected viewport height: {viewport_height}px')
                    except Exception as e:
                        viewport_height = 1000  # Fallback to 1000px
                        logger.debug(f'Failed to get viewport height, using fallback 1000px: {e}')

                    # For multiple pages (>=1.0), scroll one page at a time to ensure each scroll completes
                    if num_pages >= 1.0:
                        import asyncio

                        num_full_pages = int(num_pages)
                        remaining_fraction = num_pages - num_full_pages

                        completed_scrolls = 0

                        # Scroll one page at a time
                        for i in range(num_full_pages):
                            try:
                                pixels = viewport_height  # Use actual viewport height
                                if not down:
                                    pixels = -pixels

                                event = browser_session.event_bus.dispatch(
                                    ScrollEvent(direction=direction, amount=abs(pixels), node=node)
                                )
                                await event
                                await event.event_result(raise_if_any=True, raise_if_none=False)
                                completed_scrolls += 1

                                # Small delay to ensure scroll completes before next one
                                await asyncio.sleep(0.3)

                            except Exception as e:
                                logger.warning(f'Scroll {i + 1}/{num_full_pages} failed: {e}')
                                # Continue with remaining scrolls even if one fails

                        # Handle fractional page if present
                        if remaining_fraction > 0:
                            try:
                                pixels = int(remaining_fraction * viewport_height)
                                if not down:
                                    pixels = -pixels

                                event = browser_session.event_bus.dispatch(
                                    ScrollEvent(direction=direction, amount=abs(pixels), node=node)
                                )
                                await event
                                await event.event_result(raise_if_any=True, raise_if_none=False)
                                completed_scrolls += remaining_fraction

                            except Exception as e:
                                logger.warning(f'Fractional scroll failed: {e}')

                        if num_pages == 1.0:
                            long_term_memory = f'Scrolled {direction} {target} by one page ({viewport_height}px)'
                        else:
                            long_term_memory = f'Scrolled {direction} {target} by {completed_scrolls:.1f} pages (requested: {num_pages}, {viewport_height}px per page)'
                    else:
                        # For fractional pages <1.0, do single scroll
                        pixels = int(num_pages * viewport_height)
                        event = browser_session.event_bus.dispatch(
                            ScrollEvent(direction='down' if down else 'up', amount=pixels, node=node)
                        )
                        await event
                        await event.event_result(raise_if_any=True, raise_if_none=False)
                        long_term_memory = f'Scrolled {direction} {target} by {num_pages} pages ({viewport_height}px per page)'

                    msg = f'🔍 {long_term_memory}'
                    logger.info(msg)
                    return msg,long_term_memory
                except Exception as e:
                    logger.error(f'Failed to dispatch ScrollEvent: {type(e).__name__}: {e}')
                    error_msg = 'Failed to execute scroll action.'
                    return error_msg

    async def send_keys(self, keys: str):
                'Send strings of special keys to use e.g. Escape, Backspace, Insert, PageDown, Delete, Enter, or Shortcuts such as `Control+o`, `Control+Shift+T`'
                browser_session = await self.get_browser_session()
                try:
                    event = browser_session.event_bus.dispatch(SendKeysEvent(keys=keys))
                    await event
                    await event.event_result(raise_if_any=True, raise_if_none=False)
                    memory = f'Sent keys: {keys}'
                    msg = f'⌨️  {memory}'
                    logger.info(msg)
                    return memory
                except Exception as e:
                    logger.error(f'Failed to dispatch SendKeysEvent: {type(e).__name__}: {e}')
                    error_msg = f'Failed to send keys: {str(e)}'
                    return error_msg
    
    # deep agent

    async def deep_agent(self):
         from deepagents import create_deep_agent

         tools = self.tools_list()
         agent = create_deep_agent(
            tools=tools,
            instructions="""You are the browser agent based on user query you will interact with the current browser with available tools each tool is designed to handle something on the browser page
            You have a list of tools:
            go_to_url : navigate through the particular url
            click_element_by_index: if element is clickable then you can send the index of the element into this and it will click the element on browser
            and there are many more.

            but one tool is your guide through this browser automation which is current_page_index which will give you the current interactive elements from the browser page
            so before tacking any action make sure you have current screen exposure to you that yes right now this is the screen and based on this i have to decide what to do
            for completing the task

            """,
            model=llm
        )
         return agent
    async def run_deep_agent(self):
         agent = await self.deep_agent()
         browser_session = await self.get_browser_session()
         await browser_session.start()
         async for stream_mode, chunk in agent.astream(
        {"messages": [{"role": "user", "content": """Go to https://salesdemo.successfactors.eu/
                                                enter this company id  and go to next page
                                                take one by one action
                                                and type username box  = ""
                                                password box  = "" (these are two different fields)
                                                and click the continue button"""}]},
                    stream_mode=["updates", "messages", "custom"]
        ):
            print(stream_mode,":")
            print(chunk)
            print("\n")
            
    # Tools list
    def tools_list(self):
         tools = [self.get_dropdown_options,self.send_keys,self.go_to_url, self.click_element_by_index, self.input_text, self.wait, self.scroll,write_todos, self.current_page_index]
         return tools
    # Nodes
    async def planner(self, state:AgentState):
        """
        Plans the actions before taking any action
        """
        system_prompt = f"""
         You are planner node based on the user query plan the actions,
         {WRITE_TODOS_DESCRIPTION}

        """
        logger.info("Generating Plan...")
        todo_llm = await self.get_llm_with_tools([write_todos])
        message = await todo_llm.ainvoke([SystemMessage(content=system_prompt)]+state['messages'])
        if message.tool_calls:
            logger.info('Plan generated.')
             
  
        return {"messages": [message]}
    
    async def todo_executer(self, state: TaskExecutor):
         pass

    async def call_executor_graph(self,state: AgentState):
         todos = state['todos']
         pass
    async def assign_task(self, state:AgentState)-> Command[Literal["planner", "tools", "call_executor", "__end__"]]:
         if state['todos'] is None:
              return Command(
                   goto="planner",
                   update={"messages": [AIMessage(content="todos not found")]}
              )
         todos = state['todos']
         system_prompt = """ You are the task manager agent your task is to analyze the current todo list and action taken 
         based on that update the todo list and 
         handover the first pending todo in the list for execution
         This is the current status of the todos and update the status of current todo with write_todos tool
         {todos}

         usage of todo tool: {WRITE_TODOS_DESCRIPTION}
         """
         class TaskAssign(TypedDict):
              task: Todo
         response = llm.bind_tools([write_todos]).with_structure_output(TaskAssign)

         
    async def graph_builder(self, AgentState: AgentState):
         builder = StateGraph(AgentState)
         builder.add_node("planner",self.planner)
         builder.add_node("tools",self.tool_node)
        #  builder.add_node("call_executor",self.call_executor_graph)


         builder.add_edge(START, "planner")
         builder.add_conditional_edges("planner", tools_condition)
        #  builder.add_edge("tools","call_executor")
         
         graph = builder.compile()
         return graph
    
    async def run_graph(self, state: AgentState):
         graph = await self.graph_builder(AgentState)
         result = await graph.ainvoke(state,config={"recursion_limit": 1000})
         for m in result['messages']:
            m.pretty_print()
         return result
              
         #  print("last state",result)
        #  for m in result['messages']:
        #       m.pretty_print()
        

        #  return result

# asyncio.run(config.login_script())
# result = asyncio.run(config.run_graph(AgentState(messages=[HumanMessage(content="""Go to https://salesdemo.successfactors.eu/
                                                #  enter this company id  and go to next page
                                                #  take one by one action
                                                #  and type username box  = ""
                                                #  password box  = "" (these are two different fields)
                                                #  and click the continue button you have done your work""")])))
# asyncio.run(config.go_to_url.invoke({"url":"https://salesdemo.successfactors.eu/", "new_tab":True}))
  
    #     async for stream_mode, chunk in agent.astream(
    # {"messages": [{"role": "user", "content": """Go to https://salesdemo.successfactors.eu/
    #                                             enter this company id SFCPART001662 and go to next page
    #                                             take one by one action
    #                                             and type username box  = "sfadmin"
    #                                             password box  = "Part@dc99" (these are two different fields)
    #                                             and click the continue button you have done your work"""}]},
    #             stream_mode=["updates", "messages", "custom"],
    #             config={{"recursion_limit": 1000}}
    #     ):
                
    #         print(stream_mode,":")
    #         print(chunk)
    #         print("\n")

    
