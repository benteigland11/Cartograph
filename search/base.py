"""
Abstract base class for search backends.

A backend receives the widget list at build time and answers queries at search time.
"""


class SearchBackend:
    def build(self, widgets: list) -> None:
        """Index the widget list. Called once after library load."""
        raise NotImplementedError

    def query(self, query: str, domain_filter: str | None = None,
              language_filter: str | None = None, type_filter: str | None = None,
              top_k: int = 15) -> list[dict]:
        """
        Return a ranked list of widget dicts, each augmented with
        a 'relevance_score' key. Filtering is applied inside the backend
        so implementations can short-circuit early.
        """
        raise NotImplementedError
