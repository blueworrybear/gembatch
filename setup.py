"""Setup script for the gembatch package."""

import setuptools  # type: ignore

setuptools.setup(
    name="gembatch",
    version="0.1.0",
    description=(
        "A Python library simplifies building language chain applications with Gemini, "
        "leveraging batch mode for cost-effective prompt processing."
    ),
    python_requires=">=3.12",
    author="Benno Lin",
    author_email="blueworrybear@gmail.com",
    packages=setuptools.find_packages(include=["gembatch"]),
    package_data={
        "gembatch": ["firestore.indexes.json", "cloudbuild.yml"],
    },
    install_requires=[
        "google-cloud-aiplatform>=1.38",
        "firebase-admin>=6.5.0",
        "firebase-functions>=0.4.2",
        "requests>=2.31.0",
        "python-dotenv>=1.0.1",
        "inquirer>=3.4.0",
        "prompt_toolkit>=3.0.48",
    ],
    entry_points={
        "console_scripts": [
            "gembatch=gembatch.__main__:main",
        ],
    },
)
