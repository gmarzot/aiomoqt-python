# aiomoqt - Media over QUIC Transport (MoQT)

`aiomoqt` is an implementaion of the MoQT protocol, based on `aioquic` and `asyncio`.

## Overview

This package implements the [MoQT Specification](https://moq-wg.github.io/moq-transport/draft-ietf-moq-transport.html) (currently **draft-08**). It is desinged for general use as an MoQT client and server library. The architecture is
based on [asyncio](https://pypi.org/project/asyncio/), and extends the [aioquic](https://pypi.org/project/aioquic/) protocol. Currently most MoQT control messages are parsed and serialized. 

### Featurtes

- Serialization and deserialization of messages and data streams.
- A session protocol class with MoQT message registry.
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

    client = MOQTClientSession(host=127.0.0.1, port=443, endpoint='wt-endpoint')

    async with client.connect() as session:
        try:
            await session.client_session_init():
            response = await session.subscribe(
                'namespace', 
                'track_name',
                wait_response=True
            )
            # wait for session close, process data and control messages
            await session.async_closed()
        except MOQTException as e:
            session.close(e.error_code, e.reason_phrase)

asyncio.run(main())
```

#### see aiomoqt-python/aiomoqt/examples for additional examples

## Development

To set up a development environment:

```bash
git clone https://github.com/gmarzot/aiomoqt-python.git
cd aiomoqt-python
./bootstrap_python.sh
source .venv/bin/activate
```
## Installation

```bash
uv pip install .
```

## TODO

* Datagram Object Data
* FETCH/OK, Joining FETCH/OK, 
* Direct QUIC connection
* GOAWAY, SUBSCRIBE_UPDATE, ANNOUNCE (beyond the basic), etc.
* Move track data read/write API to aiomoqt.messages.track
* Support file I/O [MOQT File Format](https://datatracker.ietf.org/doc/html/draft-jennings-moq-file-00)
* Real tests

## Contributing

Contributions are welcome! If you'd like to contribute, please:

* Fork the repository on GitHub.
* Create a new branch for your feature or bug fix.
* Submit a pull request with a clear description of your changes.

For major changes, please open an issue first to discuss your proposal.

## Resources

- [MoQT Specification](https://moq-wg.github.io/moq-transport/draft-ietf-moq-transport.html)
- [Media Over QUIC Working Group](https://datatracker.ietf.org/wg/moq/about/)
- [`aiomoqt` GitHub Repository](https://github.com/gmarzot/aiomoqt-python)

---

## Acknowledgements

This project takes inspiration from, and has benefited from the great work done by the [Meta/moxygen](https://github.com/facebookexperimental/moxygen) team, and the efforts of the MOQ IETF WG.

