from setuptools import setup, find_packages

setup(
    name="tv-archive-transcripts",
    version="1.0.0",
    description="Download TV News Archive transcripts for politicians",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=["requests>=2.20"],
    entry_points={
        "console_scripts": [
            "tv-transcripts=tv_archive_transcripts.cli:main",
        ],
    },
)
