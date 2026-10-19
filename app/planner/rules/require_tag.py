"""Edit rule: only items with a dietary tag, in some meals ("make Thursday vegetarian")."""

from planner.constraint import ScopedItemFilter
from planner.registry import register
from planner.tags import TAGS, has_tag


@register
class RequireTag(ScopedItemFilter):
    """Inside its scope, only items that qualify for `tag` (see planner.tags)."""

    name = "require_tag"
    summary = "Some meals must match a dietary tag, such as vegetarian."
    blocked_reason = "do not match the requested tag"

    def __init__(self, tag: str, scope=None):
        if tag not in TAGS:
            raise ValueError(f"{self.name}: unknown tag {tag!r}; known: {', '.join(TAGS)}")
        super().__init__(scope)
        self.tag = tag

    def allows(self, item, slot, ctx):
        """True if the item has the tag."""
        return has_tag(item, self.tag)

    def describe_block(self, slot, ctx):
        """E.g. "are not vegetarian"."""
        return f"are not {self.tag}"

    def __repr__(self) -> str:
        return f"RequireTag({self.tag!r}, {self.scope.describe()!r})"
