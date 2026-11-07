from setuptools import setup
setup(name="orca-dot-bridge", version="0.3.2", packages=["orca_dot_bridge"],
      package_data={"orca_dot_bridge": ["automation_prompt.txt"]},
      python_requires=">=3.9", description="One-shot Dot Slack and GitHub Projects bridge",
      entry_points={"console_scripts": ["orca-dot-bridge=orca_dot_bridge.cli:main"]})
