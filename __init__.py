from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill, intent_handler
from mycroft.util.log import LOG
from pokebase import pokemon


def base_stat(mon, stat_name):
    """

    :param mon: The pokemon object created with the pokemon method
    :param stat_name: Should be "speed", "special-defense", "special-attack", "defense", or "attack"
    :return: The value of the stat as an int
    """
    stat_name = stat_name.lower()
    for stat in mon.stats:
        if stat.stat.name.lower() == stat_name:
            return int(stat.base_stat)
    raise ValueError(str(stat_name) + " is an unsupported stat.")


class PokemonSkill(MycroftSkill):

    def __init__(self):
        super(PokemonSkill, self).__init__(name="PokemonSkill")

    def _extract_pokemon(self, message):
        name = message.data["PokemonName"]
        self.set_context("PokemonName", name)
        return pokemon(name)

    # @intent_handler(IntentBuilder("PokemonTypeIntent").require("Type"))
    # def handle_pokemon_type(self, message):
    #     pass
    #
    # @intent_handler(IntentBuilder("PokemonEvolveIntent").require("Evolve"))
    # def handle_pokemon_evolve(self, message):
    #     pass

    def do_pokemon_base(self, message, stat):
        mon = self._extract_pokemon(message)
        value = base_stat(mon, stat)
        self.speak_dialog("base.stat.is", {"pokemon": mon.name, "stat": stat, "value": value})

    @intent_handler(IntentBuilder("PokemonBaseSpeed").require("Speed").optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_speed(self, message):
        self.do_pokemon_base(message, "speed")

    @intent_handler(IntentBuilder("PokemonBaseSpeed").require("Special").require("Defense").optionally("Pokemon")
                    .optionally("Base"))
    def handle_pokemon_base_special_defense(self, message):
        self.do_pokemon_base(message, "special-defense")

    @intent_handler(IntentBuilder("PokemonBaseSpeed").require("Special").require("Attack").optionally("Pokemon")
                    .optionally("Base"))
    def handle_pokemon_base_special_attack(self, message):
        self.do_pokemon_base(message, "special-attack")

    @intent_handler(IntentBuilder("PokemonBaseSpeed").require("Defense").optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_defense(self, message):
        self.do_pokemon_base(message, "defense")

    @intent_handler(IntentBuilder("PokemonBaseSpeed").require("Attack").optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_attack(self, message):
        self.do_pokemon_base(message, "attack")

    # The "stop" method defines what Mycroft does when told to stop during
    # the skill's execution. In this case, since the skill's functionality
    # is extremely simple, there is no need to override it.  If you DO
    # need to implement stop, you should return True to indicate you handled
    # it.
    #
    # def stop(self):
    #    return False


def create_skill():
    return PokemonSkill()
