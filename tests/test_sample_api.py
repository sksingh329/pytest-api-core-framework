"""
Sample API tests demonstrating the pytest-api-core framework.
Target API: JSONPlaceholder (https://jsonplaceholder.typicode.com) — free fake REST API.
"""
import pytest

from pytest_api_core.assertions import assert_that


# ---------------------------------------------------------------------------
# GET tests
# ---------------------------------------------------------------------------


@pytest.mark.api
def test_get_single_post(api_client):
    """GET /posts/1 should return a post with id=1."""
    response = api_client.get("/posts/1")

    assert_that(response).status_is(200).content_type_contains("application/json")
    assert_that(response).json_path("$.id").equals(1)
    assert_that(response).has_key("title").has_key("body").has_key("userId")


@pytest.mark.api
def test_get_all_posts(api_client):
    """GET /posts should return a non-empty list."""
    response = api_client.get("/posts")

    assert_that(response).status_is(200).is_json_list().list_length_gte(1)


@pytest.mark.api
def test_get_post_comments(api_client):
    """GET /posts/1/comments should return comments with valid email fields."""
    response = api_client.get("/posts/1/comments")

    assert_that(response).status_is(200).is_json_list()
    first = response.json()[0]
    assert "email" in first, "Each comment should have an email field"
    assert_that(response).response_time_under(5000)


# ---------------------------------------------------------------------------
# POST tests
# ---------------------------------------------------------------------------


@pytest.mark.api
def test_create_post(api_client):
    """POST /posts should create a new post and return 201 with an assigned id."""
    payload = {"title": "pytest-api-core test", "body": "created by framework", "userId": 99}
    response = api_client.post("/posts", json=payload)

    assert_that(response).status_is(201).has_key("id")
    assert_that(response).json_path("$.title").equals(payload["title"])


# ---------------------------------------------------------------------------
# PUT tests
# ---------------------------------------------------------------------------


@pytest.mark.api
def test_update_post(api_client):
    """PUT /posts/1 should replace the post."""
    payload = {"id": 1, "title": "updated title", "body": "updated body", "userId": 1}
    response = api_client.put("/posts/1", json=payload)

    assert_that(response).status_is(200)
    assert_that(response).json_path("$.title").equals("updated title")


# ---------------------------------------------------------------------------
# PATCH tests
# ---------------------------------------------------------------------------


@pytest.mark.api
def test_patch_post_title(api_client):
    """PATCH /posts/1 should partially update the post."""
    response = api_client.patch("/posts/1", json={"title": "patched title"})

    assert_that(response).status_is(200).json_path("$.title").equals("patched title")


# ---------------------------------------------------------------------------
# DELETE tests
# ---------------------------------------------------------------------------


@pytest.mark.api
def test_delete_post(api_client):
    """DELETE /posts/1 should return 200."""
    response = api_client.delete("/posts/1")
    assert_that(response).status_is(200)


# ---------------------------------------------------------------------------
# Negative / error path tests
# ---------------------------------------------------------------------------


@pytest.mark.api
def test_get_nonexistent_post(api_client):
    """GET /posts/99999 should return 404."""
    response = api_client.get("/posts/99999")
    assert_that(response).status_is(404)


# ---------------------------------------------------------------------------
# User endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.api
def test_get_users(api_client):
    """GET /users should return a list of users."""
    response = api_client.get("/users")
    assert_that(response).status_is(200).is_json_list().list_length_gte(5)


@pytest.mark.api
def test_get_user_schema(api_client):
    """GET /users/1 should conform to the expected JSON Schema."""
    schema = {
        "type": "object",
        "required": ["id", "name", "email", "username"],
        "properties": {
            "id":       {"type": "integer"},
            "name":     {"type": "string"},
            "email":    {"type": "string"},
            "username": {"type": "string"},
        },
    }
    response = api_client.get("/users/1")
    assert_that(response).status_is(200).matches_schema(schema)


# ---------------------------------------------------------------------------
# Demo: intentional failure (shows failure details in the HTML report)
# ---------------------------------------------------------------------------


@pytest.mark.api
@pytest.mark.xfail(reason="Intentional demo failure to show report failure details", strict=False)
def test_demo_failure(api_client):
    """This test is expected to fail — demonstrates HTML report failure details."""
    response = api_client.get("/posts/1")
    assert_that(response).status_is(999)  # wrong status — will fail
