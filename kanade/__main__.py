import logging

from .bot import Kanade
from .config import Config


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_env()
    Kanade(config).run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
