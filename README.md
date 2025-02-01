# MOQT Protocol Library

A Python implementation of the MOQT (Media over QUIC) protocol.

## Installation

```bash
pip install moqt
# or
uv pip install moqt
```

## Usage

Basic client usage:

```python

from moqt.client import MOQTClient

async def main():
    client = MOQTClient(host='localhost', port=4433)
    async with client.connect() as client_session
        await client_session.initialize()
        await client_session.subscribe_to_track('namespace', 'track_name')
```

## Development

To set up for development:

```bash
git clone https://github.com/yourusername/moqt.git
cd moqt
pip install -e .
```
