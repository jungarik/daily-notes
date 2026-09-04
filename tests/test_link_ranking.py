"""Idea-level ranking of link candidates, and its retrieval-order fallback."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import config
from agents.enrich.nodes.write import _rank, _shared
from agents.runtime import model_gateway


def completion(payload):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps(payload)))])


SOURCE = {"id": 1, "title": "Deadlines force scope cuts",
          "text": "A fixed date turns scope into the variable.", "path": "work",
          "tags": []}

ROWS = [
    {"note_id": 2, "title": "Sprint planning notes", "path": "work/agile",
     "tags": [], "snippet": "planning", "distance": 0.11},
    {"note_id": 3, "title": "Constraints breed creativity", "path": "ideas",
     "tags": [], "snippet": "limits", "distance": 0.44},
]


class LinkRankingTests(unittest.TestCase):
    def test_ranking_reorders_by_shared_idea(self):
        payload = {"ranked": [
            {"note_id": 3, "reason": "a constraint as the creative lever",
             "idea_link": True},
            {"note_id": 2, "reason": "same topic only", "idea_link": False},
        ]}

        with patch.object(_rank.model_gateway, "chat_completion",
                          return_value=completion(payload)):
            ranked = _rank.rank(SOURCE, ROWS, "en")

        self.assertEqual([3, 2], [row["note_id"] for row in ranked])
        self.assertEqual("a constraint as the creative lever", ranked[0]["reason"])
        self.assertTrue(ranked[0]["idea_link"])
        self.assertFalse(ranked[1]["idea_link"])

    def test_ranking_drops_invented_ids_and_keeps_forgotten_ones(self):
        payload = {"ranked": [
            {"note_id": 999, "reason": "hallucinated", "idea_link": True},
            {"note_id": 3, "reason": "real", "idea_link": True},
        ]}

        with patch.object(_rank.model_gateway, "chat_completion",
                          return_value=completion(payload)):
            ranked = _rank.rank(SOURCE, ROWS, "en")

        self.assertEqual([3, 2], [row["note_id"] for row in ranked])

    def test_model_failure_falls_back_to_retrieval_order(self):
        error = model_gateway.ModelGatewayError("model_timeout", "boom")

        with patch.object(_rank.model_gateway, "chat_completion", side_effect=error):
            ranked = _rank.rank(SOURCE, ROWS, "en")

        self.assertEqual(ROWS, ranked)

    def test_unparseable_response_falls_back_to_retrieval_order(self):
        garbage = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="not json"))])

        with patch.object(_rank.model_gateway, "chat_completion",
                          return_value=garbage):
            self.assertEqual(ROWS, _rank.rank(SOURCE, ROWS, "en"))

    def test_disabled_ranking_skips_the_model(self):
        with patch.object(config, "LINK_RANK_ENABLED", False), \
                patch.object(_rank.model_gateway, "chat_completion") as call:
            self.assertEqual(ROWS, _rank.rank(SOURCE, ROWS, "en"))

        call.assert_not_called()


class LinkCandidateTests(unittest.TestCase):
    def _candidates(self, ranked, preselect_ids=()):
        with patch.object(_shared.embedings, "embed", return_value="vector"), \
                patch.object(_shared.db, "link_candidates", return_value=ROWS), \
                patch.object(_shared.db, "owned_note_ids", return_value=set()), \
                patch.object(_shared._rank, "rank", return_value=ranked):
            return _shared._link_candidates(7, SOURCE, list(preselect_ids), "en")

    def test_idea_links_are_offered_first_and_preselected(self):
        ranked = [
            {**ROWS[1], "reason": "constraint as lever", "idea_link": True},
            {**ROWS[0], "reason": "same topic only", "idea_link": False},
        ]
        candidates, preselected = self._candidates(ranked)

        self.assertEqual([3, 2], [item["note_id"] for item in candidates])
        self.assertEqual("constraint as lever", candidates[0]["reason"])
        self.assertEqual([3], preselected)

    def test_no_idea_link_preselects_nothing_despite_close_distance(self):
        """Ranking ran and found no real connection: do not fall back to distance."""
        ranked = [{**row, "reason": "", "idea_link": False} for row in ROWS]
        _, preselected = self._candidates(ranked)

        self.assertEqual([], preselected)

    def test_distance_threshold_still_applies_when_ranking_did_not_run(self):
        _, preselected = self._candidates(list(ROWS))

        self.assertEqual([2, 3], preselected)


if __name__ == "__main__":
    unittest.main()
