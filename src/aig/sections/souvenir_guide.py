from src.aig.context import AIGContext


def build(context: AIGContext) -> dict:
    cities = []
    for city, lib in context.library.items():
        cities.append({"city": city, "items": list(lib.souvenirs)})
    return {"cities": cities}
