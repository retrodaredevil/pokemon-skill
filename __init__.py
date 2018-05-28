import re
from difflib import SequenceMatcher

from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill, intent_handler
from mycroft.util.log import LOG
from pokebase import pokemon, APIResourceList


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


def split_word(to_split):
    """Simple util method that is used throughout this file to easily split a string if needed."""
    return re.split("\W+", to_split)


# useful docs: https://mycroft-core.readthedocs.io/en/stable/source/mycroft.html#mycroftskill-class
class PokemonSkill(MycroftSkill):

    def __init__(self):
        super(PokemonSkill, self).__init__(name="PokemonSkill")
        self.pokemon_names = None  # a list of a list of strings where each sublist is the pokemon's name split in words

    def initialize(self):
        if not self.pokemon_names:
            self.pokemon_names = [name for name in APIResourceList("pokemon").names]

    def _extract_pokemon(self, message):
        def alike_amount(pokemon_name):
            """
            :param pokemon_name: Name of the pokemon as a string
            :return: A number from 0 to 1 representing how alike pokemon_name is to utterance where 1 is most alike
            """
            split_name = split_word(pokemon_name)

            name_index = 0
            equalities = []
            for s in split:
                name_compare_word = split_name[name_index]
                equality = SequenceMatcher(None, name_compare_word, s).ratio()
                if equality > .7:
                    equalities.append(equality)
                    name_index += 1
                elif name_index > 0:  # if this has already been appended to, break
                    break

                if name_index >= len(split_name):
                    break  # don't test more words than are in the pokemon's name
            return sum(equalities) / len(split_name)

        utterance = message.data["utterance"]
        split = split_word(utterance)

        name = None
        alike = 0

        i = 0
        for name_element in self.pokemon_names:
            amount = alike_amount(name_element)
            if amount > alike:
                name = name_element
                alike = amount

            i += 1
            # if i >= 50:  # in early states of development, make debugging easier
            #     break

        if not name:
            return None
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
        if not mon:
            self.speak_dialog("unable.to.find.pokemon")
            return
        value = base_stat(mon, stat)
        self.speak_dialog("base.stat.is", {"pokemon": mon.name, "stat": stat, "value": value})

    @intent_handler(IntentBuilder("PokemonBaseSpeed").require("Speed").optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_speed(self, message):
        self.do_pokemon_base(message, "speed")

    @intent_handler(IntentBuilder("PokemonBaseSpecialDefense").require("Special").require("Defense").optionally("Pokemon")
                    .optionally("Base"))
    def handle_pokemon_base_special_defense(self, message):
        self.do_pokemon_base(message, "special-defense")

    @intent_handler(IntentBuilder("PokemonBaseSpecialAttack").require("Special").require("Attack").optionally("Pokemon")
                    .optionally("Base"))
    def handle_pokemon_base_special_attack(self, message):
        self.do_pokemon_base(message, "special-attack")

    @intent_handler(IntentBuilder("PokemonBaseDefense").require("Defense").optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_defense(self, message):
        self.do_pokemon_base(message, "defense")

    @intent_handler(IntentBuilder("PokemonBaseAttack").require("Attack").optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_attack(self, message):
        self.do_pokemon_base(message, "attack")

    @intent_handler(IntentBuilder("PokemonBaseHP").require("Health").optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_attack(self, message):
        self.do_pokemon_base(message, "hp")

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
