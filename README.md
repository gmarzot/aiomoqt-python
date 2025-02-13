# MOQT Protocol Library

A Python asyncio implementation of the MoQT protocol (Media over QUIC Transport)

- [MOQT Transport Specification](https://moq-wg.github.io/moq-transport/draft-ietf-moq-transport.html)
- [Media Over QUIC Working Group](https://datatracker.ietf.org/wg/moq/about/)
- [aiomoqt-python GitHub Repo](https://github.com/gmarzot/aiomoqt-python)

This package is intended faithfully implement the Media over QUIC Transport protocol following the latest draft (currently draft8). The package is built on top of aioquic and follows the asyncio design pattern. The session protocol class maintains an MOQT message registry mapping control message types to messase class (serliaze, deserialize) and an unbound class method to handle responses and incoming messages. The high level client session API supports both async and synchronous calls via the wait_response flag.

NOTE: this package should be considered alpha 
## Installation

```bash
pip install aiomoqt
# or
uv pip install aiomoqt
```

## Usage

Basic client usage:

```python
import asyncio
from aiomoqt.client import MOQTClient

async def main():
    client = MOQTClient(host='localhost', port=4433)
    async with client.connect() as session
        await session.initialize()
        response = await session.subscribe('namespace', 'track_name', wait_response=True)
        
asyncio.run(main())
```

## Development

To set up for development:

```bash
git clone https://github.com/gmarzot/aiomoqt-python.git
cd aiomoqt-python
./bootstrap_python.sh
source .venv/bin/activate
uv pip install .
```
