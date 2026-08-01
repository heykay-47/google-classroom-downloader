import argparse
import pathlib

TOKEN = "__WEB_IMAGE__"
TEMPLATE = pathlib.Path(__file__).with_name("cloud-run-service.yaml")


def render_service(web_image: str) -> str:
    if not web_image or "://" in web_image or " " in web_image:
        raise ValueError("Provide a container image reference")
    text = TEMPLATE.read_text(encoding="utf-8")
    if text.count(TOKEN) != 1:
        raise RuntimeError("Cloud Run template must contain one web image token")
    return text.replace(TOKEN, web_image)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--output", default="deploy/cloud-run-service.rendered.yaml")
    args = parser.parse_args()
    pathlib.Path(args.output).write_text(render_service(args.web_image), encoding="utf-8")


if __name__ == "__main__":
    main()
