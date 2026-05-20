"""Empty conftest at project root.

Its presence tells pytest this is the rootdir, so `from core.money import ...`
in test files resolves correctly without any extra path manipulation.
"""
