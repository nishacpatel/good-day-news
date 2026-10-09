import pytest

from gooddaynews.feedback import record, state_from_rows


def test_latest_reaction_wins():
    s = state_from_rows([("like", 1, None), ("dislike", 1, None), ("like", 2, None), ("unlike", 2, None),
                         ("dislike", 3, None)])
    assert s.liked == set() and s.disliked == {1, 3}


def test_saved_list_is_most_recent_first_and_respects_unsave():
    s = state_from_rows([("save", 1, None), ("save", 2, None), ("save", 3, None), ("unsave", 2, None),
                         ("save", 1, None)])
    assert s.saved == [1, 3]


def test_topic_and_source_follows_toggle():
    s = state_from_rows([
        ("hide_topic", None, "culture"), ("follow_topic", None, "science"), ("follow_topic", None, "people"),
        ("unfollow_topic", None, "people"), ("follow_source", None, "bbc.co.uk"), ("unhide_topic", None, "culture"),
        ("hide_topic", None, "progress"),
    ])
    assert s.hidden_pillars == {"progress"}
    assert s.followed_pillars == {"science"}
    assert s.followed_sources == {"bbc.co.uk"}


def test_events_do_not_change_state():
    s = state_from_rows([("share", 1, None), ("read", 1, None), ("open_source", 1, None)])
    assert not (s.liked or s.saved or s.hidden_pillars)


def test_unknown_actions_are_rejected():
    with pytest.raises(ValueError):
        record(None, "u", "delete_everything", 1)
