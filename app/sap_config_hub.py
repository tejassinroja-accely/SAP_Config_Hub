from typing import Optional
from browser_use.browser.session import BrowserSession
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from app.config import settings


class SapConfigHub:
    def __init__(self,company_id,username,password):
        self._SAP_Company_Id = company_id
        self._sap_username = username
        self._sap_password = password
        self._browser_session: Optional[BrowserSession] = None
        self.browser_state_summary = None

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
    

config = SapConfigHub(company_id=settings.company_id,username=settings.username, password=settings.password)
import asyncio

asyncio.run(config.login_script())