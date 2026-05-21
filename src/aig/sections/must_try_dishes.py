from src.aig.context import AIGContext


def build(context: AIGContext) -> dict:
    cities = []
    for city, lib in context.library.items():
        cities.append({"city": city, "dishes": list(lib.local_dishes)})
    return {"cities": cities}
