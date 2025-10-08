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
)

# app
from app.config import setup_logger
from app.config import settings
from app.config import llm

# langchain
from langchain_core.tools import tool
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

# langgraph
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

# utility
from typing import Optional, TypedDict, NotRequired, Annotated
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
        self._browser_session = await self.get_browser_session()
        try:
            await self._browser_session.start()
            await self._browser_session.navigate_to("https://salesdemo.successfactors.eu/")
            await asyncio.sleep(3)
            page = await self.current_page_index()
            print("/n")
            print(page)

        except Exception as e:
            print("error:",e)
        finally:
            await self._browser_session.kill()

    async def get_browser_session(self) -> BrowserSession:
        if self._browser_session is None:
            self._browser_session = BrowserSession()
        return self._browser_session

    async def get_llm_with_tools(self, tools):
         llm_with_tool = llm.bind_tools(tools)
         return llm_with_tool
    
    async def current_page_index(self):
        """
        Use this fucntion to get the interactive element index
        """
        session = await self.get_browser_session()
        browser_state_summary = await session.get_browser_state_summary()
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

    @tool
    async def go_to_url(self, params: GoToUrlAction):
                """
                'Navigate to URL, set new_tab=True to open in new tab, False to navigate in current tab'
                """
                try:
                    # Dispatch navigation event
                    browser_session = await self.get_browser_session()
                    event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=params.url, new_tab=params.new_tab))
                    await event
                    await event.event_result(raise_if_any=True, raise_if_none=False)

                    if params.new_tab:
                        memory = f'Opened new tab with URL {params.url}'
                        msg = f'🔗  Opened new tab with url {params.url}'
                    else:
                        memory = f'Navigated to {params.url}'
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
                        site_unavailable_msg = f'Navigation failed - site unavailable: {params.url}'
                        browser_session.logger.warning(f'⚠️ {site_unavailable_msg} - {error_msg}')
                        return site_unavailable_msg
                    else:
                        # Return error in ActionResult instead of re-raising
                        return f'Navigation failed: {str(e)}'
    @tool
    async def wait(self,seconds: int = 3):
            """
            'Wait for x seconds (default 3) (max 30 seconds). This can be used to wait until the page is fully loaded.'
            """
            actual_seconds = min(max(seconds - 3, 0), 30)
            memory = f'Waited for {seconds} seconds'
            logger.info(f'🕒 waited for {actual_seconds} seconds + 3 seconds for LLM call')
            await asyncio.sleep(actual_seconds)
            return memory
    
    @tool
    async def click_element_by_index(self,params: ClickElementAction):
                """
                'Click element by index. Only indices from your browser_state are allowed. Never use an index that is not inside your current browser_state. Set while_holding_ctrl=True to open any resulting navigation in a new tab.'
                """
                # Dispatch click event with node
                try:
                    assert params.index != 0, (
                        'Cannot click on element with index 0. If there are no interactive elements use scroll(), wait(), refresh(), etc. to troubleshoot'
                    )
                    browser_session = await self.get_browser_session()
                    # Look up the node from the selector map
                    node = await browser_session.get_element_by_index(params.index)
                    if node is None:
                        raise ValueError(f'Element index {params.index} not found in browser state')

                    event = browser_session.event_bus.dispatch(
                        ClickElementEvent(node=node, while_holding_ctrl=params.while_holding_ctrl or False)
                    )
                    await event
                    # Wait for handler to complete and get any exception or metadata
                    click_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)
                    memory = 'Clicked element'

                    if params.while_holding_ctrl:
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
                                params=GetDropdownOptionsAction(index=params.index), browser_session=browser_session
                            )
                        except Exception as dropdown_error:
                            logger.error(
                                f'Failed to get dropdown options as shortcut during click_element_by_index on dropdown: {type(dropdown_error).__name__}: {dropdown_error}'
                            )
                        return 'Can not click on select elements.'

                    return e
                except Exception as e:
                    error_msg = f'Failed to click element {params.index}: {str(e)}'
                    return error_msg
    @tool
    async def get_dropdown_options(self,params: GetDropdownOptionsAction):
                """
                Get all options from a native dropdown or ARIA menu
                """
                # Look up the node from the selector map
                browser_session = await self.get_browser_session()
                node = await browser_session.get_element_by_index(params.index)
                if node is None:
                    raise ValueError(f'Element index {params.index} not found in browser state')

                # Dispatch GetDropdownOptionsEvent to the event handler

                event = browser_session.event_bus.dispatch(GetDropdownOptionsEvent(node=node))
                dropdown_data = await event.event_result(timeout=3.0, raise_if_none=True, raise_if_any=True)

                if not dropdown_data:
                    raise ValueError('Failed to get dropdown options - no data returned')

                # Use structured memory from the handler
                return dropdown_data
    @tool
    async def input_text(self,
        params: InputTextAction,
        has_sensitive_data: bool = False,
        sensitive_data: dict[str, str | dict[str, str]] | None = None,
    ):
        'Input text into an input interactive element. Only input text into indices that are inside your current browser_state. Never input text into indices that are not inside your current browser_state.'
        # Look up the node from the selector map
        browser_session = await self.get_browser_session()
        node = await browser_session.get_element_by_index(params.index)
        if node is None:
            raise ValueError(f'Element index {params.index} not found in browser state')

        # Dispatch type text event with node
        try:
            # Detect which sensitive key is being used
            sensitive_key_name = None
            if has_sensitive_data and sensitive_data:
                sensitive_key_name = _detect_sensitive_key_name(params.text, sensitive_data)

            event = browser_session.event_bus.dispatch(
                TypeTextEvent(
                    node=node,
                    text=params.text,
                    clear_existing=params.clear_existing,
                    is_sensitive=has_sensitive_data,
                    sensitive_key_name=sensitive_key_name,
                )
            )
            await event
            input_metadata = await event.event_result(raise_if_any=True, raise_if_none=False)

            # Create message with sensitive data handling
            if has_sensitive_data:
                if sensitive_key_name:
                    msg = f'Input {sensitive_key_name} into element {params.index}.'
                    log_msg = f'Input <{sensitive_key_name}> into element {params.index}.'
                else:
                    msg = f'Input sensitive data into element {params.index}.'
                    log_msg = f'Input <sensitive> into element {params.index}.'
            else:
                msg = f"Input '{params.text}' into element {params.index}."
                log_msg = msg

            logger.debug(log_msg)

            # Include input coordinates in metadata if available
            return msg, input_metadata if isinstance(input_metadata, dict) else None
        except BrowserError as e:
            return e
        except Exception as e:
            # Log the full error for debugging
            logger.error(f'Failed to dispatch TypeTextEvent: {type(e).__name__}: {e}')
            error_msg = f'Failed to input text into element {params.index}: {e}'
            return error_msg
    @tool
    async def scroll(self, params: ScrollAction):
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
                    if params.frame_element_index is not None and params.frame_element_index != 0:
                        node = await browser_session.get_element_by_index(params.frame_element_index)
                        if node is None:
                            # Element does not exist
                            msg = f'Element index {params.frame_element_index} not found in browser state'
                            return msg

                    direction = 'down' if params.down else 'up'
                    target = (
                        'the page'
                        if params.frame_element_index is None or params.frame_element_index == 0
                        else f'element {params.frame_element_index}'
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
                    if params.num_pages >= 1.0:
                        import asyncio

                        num_full_pages = int(params.num_pages)
                        remaining_fraction = params.num_pages - num_full_pages

                        completed_scrolls = 0

                        # Scroll one page at a time
                        for i in range(num_full_pages):
                            try:
                                pixels = viewport_height  # Use actual viewport height
                                if not params.down:
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
                                if not params.down:
                                    pixels = -pixels

                                event = browser_session.event_bus.dispatch(
                                    ScrollEvent(direction=direction, amount=abs(pixels), node=node)
                                )
                                await event
                                await event.event_result(raise_if_any=True, raise_if_none=False)
                                completed_scrolls += remaining_fraction

                            except Exception as e:
                                logger.warning(f'Fractional scroll failed: {e}')

                        if params.num_pages == 1.0:
                            long_term_memory = f'Scrolled {direction} {target} by one page ({viewport_height}px)'
                        else:
                            long_term_memory = f'Scrolled {direction} {target} by {completed_scrolls:.1f} pages (requested: {params.num_pages}, {viewport_height}px per page)'
                    else:
                        # For fractional pages <1.0, do single scroll
                        pixels = int(params.num_pages * viewport_height)
                        event = browser_session.event_bus.dispatch(
                            ScrollEvent(direction='down' if params.down else 'up', amount=pixels, node=node)
                        )
                        await event
                        await event.event_result(raise_if_any=True, raise_if_none=False)
                        long_term_memory = f'Scrolled {direction} {target} by {params.num_pages} pages ({viewport_height}px per page)'

                    msg = f'🔍 {long_term_memory}'
                    logger.info(msg)
                    return msg,long_term_memory
                except Exception as e:
                    logger.error(f'Failed to dispatch ScrollEvent: {type(e).__name__}: {e}')
                    error_msg = 'Failed to execute scroll action.'
                    return error_msg
    @tool
    async def send_keys(self, params: SendKeysAction):
                'Send strings of special keys to use e.g. Escape, Backspace, Insert, PageDown, Delete, Enter, or Shortcuts such as `Control+o`, `Control+Shift+T`'
                browser_session = await self.get_browser_session()
                try:
                    event = browser_session.event_bus.dispatch(SendKeysEvent(keys=params.keys))
                    await event
                    await event.event_result(raise_if_any=True, raise_if_none=False)
                    memory = f'Sent keys: {params.keys}'
                    msg = f'⌨️  {memory}'
                    logger.info(msg)
                    return memory
                except Exception as e:
                    logger.error(f'Failed to dispatch SendKeysEvent: {type(e).__name__}: {e}')
                    error_msg = f'Failed to send keys: {str(e)}'
                    return error_msg

    # Tools list

    def tools_list(self):
         tools = [self.get_dropdown_options,self.send_keys,self.go_to_url, self.click_element_by_index, self.input_text, self.wait, self.scroll,write_todos]
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
    async def call_executor_graph(self,state: AgentState):
         todos = state['todos']

         pass
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
         result = await graph.ainvoke(state)
         for m in result['messages']:
            m.pretty_print()
         return result
              
         #  print("last state",result)
        #  for m in result['messages']:
        #       m.pretty_print()
        

        #  return result

config = SapConfigHub(company_id=settings.company_id,username=settings.username, password=settings.password)
import asyncio
# asyncio.run(config.login_script())
asyncio.run(config.run_graph(AgentState(messages=[HumanMessage(content="Go to the url of successfactors then put company id then click continue then put username then put password then clikc continue and you are logged in")])))
