# MOQT Protocol Library

A Python asyncio implementation of the MOQT (Media over QUIC) protocol.

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
from aiomoqt.client import MOQTClient, connect

async def main():
    client = MOQTClient(host='localhost', port=4433)
    async with client.connect() as client_session
        await client_session.initialize()
        client_session.subscribe('namespace', 'track_name')
```

## Development

To set up for development:

```bash
git clone https://github.com/gmarzot/aiomoqt-python.git
cd aiomoqt-python
./bootstra_python.sh
source .venv/bin/activate
uv pip install .
```
