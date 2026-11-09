"""Tests for the SKILLS subsystem (runtime, store and REST surface).

These files cover the defects found in the skills audit: unreachable seeded
skills, a promotion gate that disagreed with the selector, trigger patterns
that matched everything, routes that discarded the submitted fields and a
store that never noticed new files.
"""
