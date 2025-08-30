# --------------------------------------------------------------------------
# package setup module
# --------------------------------------------------------------------------
from setuptools import find_packages, setup  # type: ignore

install_requires: list[str] = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
]

setup(
    name="bifrost",
    description="[FastAPI-fastkit templated] API gateway server",
    author="bnbong",
    author_email=f"bbbong9@gmail.com",
    packages=find_packages(where="src"),
    requires=["python (>=3.12)"],
    install_requires=install_requires,
)
