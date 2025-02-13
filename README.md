# aiomoqt - Media over QUIC Transport (MoQT)

`aiomoqt` is an implementaion of the MoQT protocol, based on `aioquic` and `asyncio`.

## Overview

This package aims to faithfully implement the [MoQT Specification](https://moq-wg.github.io/moq-transport/draft-ietf-moq-transport.html) (currently **draft-08**). It is desinged and intended to satisfy a variety of use-cases to operate as a test tool, faciliate education, and adoption of the protocol. It is also designed to support a variety of production use cases (TBD). 

### Featurtes

- A session protocol class maintaining an MoQT message registry for control message types.
- Serialization and deserialization of messages and data streams.
- An extensible API allowing custom handlers for responses and incoming messages.
- Support for both asynchronous and synchronous calls using the `wait_response` flag.

🚀 **Status:** Alpha

## Installation

Install using `pip`:

```bash
pip install aiomoqt
```

Or using `uv`:

```bash
uv pip install aiomoqt
```

## Usage

### Basic Client Example

```python
import asyncio
from aiomoqt.client import MOQTClientSession

async def main():
    client = MOQTClientSession(host='localhost', port=4433)
    async with client.connect() as session:
        response = await session.initialize()
        response = await session.subscribe('namespace', 'track_name', wait_response=True)
        await session._moqt_session_close

asyncio.run(main())
```

#### see aiomoqt-python/aiomoqt/examples for more additional examples

## Development

To set up a development environment:

```bash
git clone https://github.com/gmarzot/aiomoqt-python.git
cd aiomoqt-python
./bootstrap_python.sh
source .venv/bin/activate
uv pip install .
```
## Contributing

Contributions are welcome! If you'd like to contribute, please:

* Fork the repository on GitHub.
* Create a new branch for your feature or bug fix.
* Submit a pull request with a clear description of your changes.

For major changes, please open an issue first to discuss your proposal.

## Resources

- [MoQT Transport Specification](https://moq-wg.github.io/moq-transport/draft-ietf-moq-transport.html)
- [Media Over QUIC Working Group](https://datatracker.ietf.org/wg/moq/about/)
- [`aiomoqt` GitHub Repository](https://github.com/gmarzot/aiomoqt-python)

---

## Acknowledgements

This project takes inspiration from, and has benefited from the great work done by the [Meta/moxygen](https://github.com/facebookexperimental/moxygen) team, and the efforts of the MOQ IETF WG.

