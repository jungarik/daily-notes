"""Write phase: stage or validate the actual write before it commits.

link → stage (interactive) / validate (plan), each a node module with a single
public `run`; `_shared` holds the guardrails, summaries, and link-candidate
lookup they share.
"""
