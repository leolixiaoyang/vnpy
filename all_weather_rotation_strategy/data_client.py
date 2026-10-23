"""Legacy SDK alias. Does not create a client until explicitly instantiated."""
from quantlab.data.transports import SDKTransport

class TinyshareClient(SDKTransport):
    def __init__(self, token=None, client=None, **kwargs):
        super().__init__("tinyshare", client=client, token=token)
