"""Integration test package.

Tests here require a live PostgreSQL instance and are tagged with the
``integration`` pytest marker.  Run them with::

    pytest -m integration

Skip them in normal CI by omitting the ``-m integration`` flag.
"""
