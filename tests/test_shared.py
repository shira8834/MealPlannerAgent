"""Basic tests for the shared code. No AI, no API key, no network."""
import pytest

from shared import domain
from shared.memory_store import MemoryStore


@pytest.fixture
def store(tmp_path):
    """A fresh memory file in a temp folder for every test."""
    return MemoryStore(tmp_path / "memory.json")


# ---------- recipes.json ----------

def test_recipes_file_is_valid():
    recipes = domain.load_recipes()
    assert len(recipes) >= 15
    ids = [r["id"] for r in recipes]
    assert len(ids) == len(set(ids)), "recipe ids must be unique"
    for r in recipes:
        assert r["meal"] in domain.MEAL_TYPES
        assert r["ingredients"], f"{r['id']} has no ingredients"


# ---------- search_recipes ----------

def test_search_by_ingredient():
    result = domain.search_recipes(query="lentils")
    assert [r["id"] for r in result["recipes"]] == ["r06"]


def test_search_vegan_filter():
    result = domain.search_recipes(diet="vegan", limit=50)
    recipes = {r["id"]: r for r in domain.load_recipes()}
    assert result["count"] > 0
    for r in result["recipes"]:
        assert "vegan" in recipes[r["id"]]["tags"]


def test_search_avoid_matches_part_of_name():
    # "peanut" must remove "peanut butter" (r14)
    result = domain.search_recipes(meal="dinner", avoid=["peanut"], limit=50)
    assert "r14" not in [r["id"] for r in result["recipes"]]


def test_search_output_is_short():
    result = domain.search_recipes(limit=3)
    assert len(result["recipes"]) == 3
    assert result["count"] >= 15
    assert set(result["recipes"][0]) == {"id", "name", "meal", "minutes"}


def test_search_bad_meal_raises():
    with pytest.raises(ValueError):
        domain.search_recipes(meal="snack")


# ---------- save_preference + memory on disk ----------

def test_preference_survives_new_store_instance(store):
    domain.save_preference(store, "diet", "vegan")
    # A new object reading the same file = a new session
    new_store = MemoryStore(store.path)
    assert new_store.get_preferences()["diet"] == "vegan"


def test_new_preference_replaces_old(store):
    domain.save_preference(store, "diet", "vegan")
    result = domain.save_preference(store, "diet", "vegetarian")
    assert result["previous"] == "vegan"
    assert MemoryStore(store.path).get_preferences()["diet"] == "vegetarian"


def test_avoid_accepts_comma_text(store):
    result = domain.save_preference(store, "avoid", "Peanuts, fish")
    assert result["value"] == ["peanuts", "fish"]


def test_bad_preference_key_raises(store):
    with pytest.raises(ValueError):
        domain.save_preference(store, "favorite_color", "blue")


# ---------- plan_meals ----------

def test_plan_uses_saved_preferences(store):
    domain.save_preference(store, "diet", "vegan")
    domain.save_preference(store, "avoid", ["peanut"])
    domain.save_preference(store, "max_minutes", 40)
    result = domain.plan_meals(store, days=3)
    # Vegan dinners up to 40 minutes without peanuts: r11, r13
    saved = store.get_last_plan()["days"]
    assert [d["dinner"] for d in saved] == ["r11", "r13", "r11"]
    assert result["days"][0]["dinner"] == "r11 Pasta with Tomato Sauce"


def test_plan_with_no_matching_recipes_raises(store):
    domain.save_preference(store, "max_minutes", 1)
    with pytest.raises(ValueError):
        domain.plan_meals(store, days=2)


def test_plan_bad_days_raises(store):
    with pytest.raises(ValueError):
        domain.plan_meals(store, days=10)


# ---------- create_shopping_list ----------

def test_shopping_list_adds_amounts():
    # r01 (4 tomatoes, 2 tbsp oil) + r11 (4 tomatoes, 2 tbsp oil)
    result = domain.create_shopping_list(store=None, recipe_ids=["r01", "r11"])
    assert "tomatoes: 8 pcs" in result["items"]
    assert "olive oil: 4 tbsp" in result["items"]


def test_shopping_list_from_saved_plan(store):
    domain.plan_meals(store, days=2, meals=["breakfast"])
    # Next session: a new store reads the plan from disk
    result = domain.create_shopping_list(MemoryStore(store.path))
    assert result["count"] > 0
    assert "eggs: 4 pcs" in result["items"]  # day 1 breakfast = r01 Shakshuka


def test_shopping_list_without_plan_raises(store):
    with pytest.raises(ValueError):
        domain.create_shopping_list(store)


def test_shopping_list_unknown_id_raises():
    with pytest.raises(ValueError):
        domain.create_shopping_list(store=None, recipe_ids=["r99"])
