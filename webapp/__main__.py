"""``python -m webapp`` -- serve the demonstration UI on localhost."""
from __future__ import annotations

import argparse


def main(argv=None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--reload', action='store_true', help='Restart on source changes')
    args = parser.parse_args(argv)
    print(f'VIO Mapper UI: http://{args.host}:{args.port}')
    uvicorn.run('webapp.api:app', host=args.host, port=args.port, reload=args.reload)


if __name__ == '__main__':
    main()
