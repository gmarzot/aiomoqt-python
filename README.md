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
from moqt.protocol import MOQTProtocol
from moqt.messages import MessageTypes

async def main():
    client = MOQTClient()
    await client.initialize(host='localhost', port=4433)
    await client.subscribe('namespace', 'track_name')
```

## Development

To set up for development:

```bash
git clone https://github.com/yourusername/moqt.git
cd moqt
pip install -e .
```
