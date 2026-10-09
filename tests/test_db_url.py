import pytest

from gooddaynews.db import parse_database_url


def test_pooler_url():
    u = parse_database_url("postgresql://postgres.abcd:secret@aws-1-ap-south-1.pooler.supabase.com:5432/postgres")
    assert (u.user, u.password, u.host, u.port, u.database) == (
        "postgres.abcd", "secret", "aws-1-ap-south-1.pooler.supabase.com", 5432, "postgres")


def test_password_with_special_characters():
    # Characters like @ [ ] # / break the standard URL parser; the host comes after the last @.
    u = parse_database_url("postgresql://postgres.abcd:p@ss[w]#rd/1@aws-0-eu-west-1.pooler.supabase.com:6543/postgres")
    assert u.password == "p@ss[w]#rd/1" and u.host == "aws-0-eu-west-1.pooler.supabase.com" and u.port == 6543


def test_percent_encoded_password_and_defaults():
    u = parse_database_url("postgres://postgres:a%40b@db.example.supabase.co")
    assert u.password == "a@b" and u.port == 5432 and u.database == "postgres"


def test_rejects_non_urls():
    with pytest.raises(ValueError):
        parse_database_url("not a url")
