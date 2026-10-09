"""
cap.py: salary-cap math shared by the AI drafters and the human-pick warnings.

The question it answers: if this team drafts player p right now, can it still fill every
other open roster slot with undrafted players and stay under the cap?

The cheapest way to fill the open slots is simple for these rosters: each specific-position
slot takes the cheapest undrafted player at that position, then the "free" slots (UT, then
FLEX) take the cheapest of whoever is left. That is exact for this slot structure.
"""
from collections import Counter


def salary_of(player):
    """Salary as a number. Baseball uses s_sal, basketball and football use Salary."""
    raw = player.get("s_sal") or player.get("Salary")
    if raw is None:
        return 0.0
    try:
        return float(str(raw).replace("$", "").replace(",", "").strip())
    except ValueError:
        return 0.0


class CapRules:
    """natural(p):  the slot label a player naturally belongs to.
    free:        {label: can_fill(p)} for slots that take more than one kind of player,
                 in fill order (restricted ones like UT before FLEX).
    priority(p): the slot labels a pick tries, in order."""

    def __init__(self, natural, free, priority):
        self.natural = natural
        self.free = free
        self.priority = priority


class CapChecker:
    def __init__(self, rules, pool, open_slots, spent, cap, twin_map=None, safety=1.0):
        self.rules = rules
        self.cap = float(cap)
        self.spent = float(spent)
        self.safety = safety
        self.open = Counter(open_slots)
        self.twin_map = twin_map or {}
        self.by_id = {str(p.get("id")): p for p in pool}

        ranked = sorted(((salary_of(p), str(p.get("id"))) for p in pool), key=lambda t: t[0])
        players = {str(p.get("id")): p for p in pool}
        self.by_label = {}
        self.free_lists = {label: [] for label in rules.free}
        for sal, pid in ranked:
            if sal <= 0:                  # no salary on file: a team can't count on that player
                continue
            p = players[pid]
            nat = rules.natural(p)
            if nat and nat not in rules.free:
                self.by_label.setdefault(nat, []).append((sal, pid))
            for label, can_fill in rules.free.items():
                if can_fill(p):
                    self.free_lists[label].append((sal, pid))

    def _slot_for(self, player, counts):
        for label in self.rules.priority(player):
            if label and counts.get(label, 0) > 0:
                return label
        return None

    def _fill_cost(self, counts, used):
        """Cheapest total salary to fill every slot in counts, or None if some slot can't be filled."""
        used = set(used)
        total = 0.0

        # specific-position slots first: the cheapest player at that position
        for label, n in counts.items():
            if n <= 0 or label in self.rules.free:
                continue
            got = 0
            for sal, pid in self.by_label.get(label, ()):
                if pid in used:
                    continue
                used.add(pid)
                total += sal
                got += 1
                if got == n:
                    break
            if got < n:
                return None

        # then the free slots, restricted ones (UT) before FLEX
        for label in self.rules.free:
            n = counts.get(label, 0)
            got = 0
            for sal, pid in self.free_lists[label]:
                if got == n:
                    break
                if pid in used:
                    continue
                used.add(pid)
                total += sal
                got += 1
            if got < n:
                return None

        return total

    def evaluate(self, player):
        """(salary added by this pick, cheapest cost to fill the other open slots, slots left after),
        or None if it can't be judged."""
        pid = str(player.get("id"))
        counts = Counter(self.open)
        spend = salary_of(player)
        used = {pid}

        label = self._slot_for(player, counts)
        if label is None:
            return None
        counts[label] -= 1

        twin = self.by_id.get(self.twin_map.get(pid))
        if twin is not None:                          # two-way: both salaries, plus an extra FLEX slot
            used.add(str(twin.get("id")))
            spend += salary_of(twin)
            counts["FLEX"] += 1
            twin_label = self._slot_for(twin, counts)
            if twin_label is None:
                return None
            counts[twin_label] -= 1

        reserve = self._fill_cost(counts, used)
        if reserve is None:
            return None
        return spend, reserve, sum(n for n in counts.values() if n > 0)

    def feasible(self, player):
        """AI check: after this pick, can the team still finish its roster under the cap (with a cushion)?"""
        if self.spent + salary_of(player) > self.cap:
            return False
        result = self.evaluate(player)
        if result is None:
            return True                               # can't judge (e.g. the pool can't fill a slot anyway)
        spend, reserve, _ = result
        return self.spent + spend + reserve * self.safety <= self.cap

    def warning(self, player, tight=1.25):
        """Human check: None if fine, otherwise {'level': 'over' | 'short' | 'tight', ...}."""
        result = self.evaluate(player)
        spend = result[0] if result else salary_of(player)
        reserve = result[1] if result else 0.0
        slots = result[2] if result else 0
        left = self.cap - self.spent - spend

        info = {"left": left, "reserve": reserve, "slots": slots}
        if left < 0:
            return {"level": "over", **info}
        if result is None:
            return None
        if left < reserve:
            return {"level": "short", **info}
        if reserve > 0 and left < reserve * tight:
            return {"level": "tight", **info}
        return None