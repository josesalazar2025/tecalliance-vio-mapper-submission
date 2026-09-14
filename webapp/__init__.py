"""FastAPI service and static frontend for the live mapping demonstration.

The mapper is imported, never reimplemented: every number this package serves is
read back off the same results/evidence frames the workbook is built from, so the
screen and the downloaded file can never disagree.
"""
