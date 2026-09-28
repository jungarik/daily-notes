"""Write phase: stage or validate the actual write before it commits.

link → stage (interactive) / validate (plan), each a node module with a single
public `run`. Each node owns its own guardrails and summary builders — they are
mappers, so they are duplicated rather than shared.
"""
