import re
from difflib import SequenceMatcher

from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill, intent_handler
from mycroft.util.log import LOG
from pokebase import pokemon, APIResourceList, pokemon_species


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


def attr(obj, key):
    if isinstance(obj, dict):
        return obj[key]
    return obj.__getattribute__(key)


def split_word(to_split):
    """Simple util method that is used throughout this file to easily split a string if needed."""
    return re.split("\W+", to_split)


# useful docs: https://mycroft-core.readthedocs.io/en/stable/source/mycroft.html#mycroftskill-class
class PokemonSkill(MycroftSkill):

    def __init__(self):
        super(PokemonSkill, self).__init__(name="PokemonSkill")
        self.pokemon_names = None  # a list of a list of strings where each sublist is the pokemon's name split in words
        self.last_pokemon = None

    def initialize(self):
        if not self.pokemon_names:
            self.pokemon_names = [name for name in APIResourceList("pokemon").names]

    def _lang(self, message):
        return message.data.get("lang", None)

    def _get_name_from_lang(self, names, lang=None):
        if not names:
            return None
        lang = (lang or "en-us").split("-")  # lang[0] is language, lang[1] is country

        best_name = None
        for name in names:
            if name.language.name == lang[0]:
                best_name = name.name
                if name.language.iso3166 == lang[1]:
                    return best_name

        return best_name or names[0].name

    def _pokemon_name(self, mon, lang=None):
        """
        :param mon: The pokemon object created with the pokemon method
        :return: A more readable/friendly version of the pokemon's name
        """
        return self._get_name_from_lang(mon.forms[0].names, lang) or mon.name

    def _species_name(self, species, lang=None):
        return self._get_name_from_lang(species.names, lang) or species.name

    def _form_name(self, mon, lang=None):
        """
        :param mon: The pokemon object created with the pokemon method
        :return: A readable/friendly version of the pokemon's form or None if the pokemon isn't in a form
        """
        form = mon.forms[0]
        return self._get_name_from_lang(form.form_names, lang) or None

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
            return sum(equalities)

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

    def _check_pokemon(self, mon):
        """
        :param mon: The pokemon object created from pokemon() (or possibly None)
        :return: The pokemon you should use. If None, where ever you called this, just return
        """
        if not mon:
            if not self.last_pokemon:
                self.speak_dialog("unable.to.find.pokemon")
                return None
            else:
                mon = self.last_pokemon
        self.last_pokemon = mon
        return mon

    @intent_handler(IntentBuilder("PokemonTypeIntent").require("Type"))
    def handle_pokemon_type(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        types = mon.types

        if len(types) == 1:
            self.speak_dialog("pokemon.type.one", {"pokemon": mon.name, "type1": types[0].type.name})
        else:
            self.speak_dialog("pokemon.type.two", {"pokemon": mon.name, "type1": types[0].type.name,
                                                   "type2": types[1].type.name})

    @intent_handler(IntentBuilder("PokemonEvolveIntent").require("Evolve").require("Into"))
    def handle_pokemon_evolve_into(self, message):
        def find_species_chain(chain):
            for evolution_chain in attr(chain, "evolves_to"):
                if attr(attr(chain, "species"), "name") == name:
                    return evolution_chain
                r = find_species_chain(evolution_chain)
                if r:
                    return r
            return None

        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        name = mon.species.name  # used in find_species_chain
        into = attr(find_species_chain(mon.species.evolution_chain.chain), "evolves_to")
        names_into = []
        for evolution in into:
            names_into.append(str(self._species_name(pokemon_species(
                attr(attr(evolution, "species"), "name"))
            )))

        self.speak_dialog("pokemon.evolves.into.dialog", {"pokemon": self._pokemon_name(mon),
                                                          "evolve": ", ".join(names_into)})

    @intent_handler(IntentBuilder("PokemonFormIntent").require("Form"))
    def handle_pokemon_form(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        lang = self._lang(message)
        pokemon_name = self._pokemon_name(mon, lang)
        form_name = self._form_name(mon, lang)
        if not form_name:
            self.speak_dialog("pokemon.has.no.forms", {"pokemon": pokemon_name})
            return

        self.speak_dialog("pokemon.is.in.form", {"pokemon": pokemon_name, "form": form_name})

    def do_pokemon_base(self, message, stat):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        value = base_stat(mon, stat)
        self.speak_dialog("base.stat.is", {"pokemon": self._pokemon_name(mon, self._lang(message)),
                                           "stat": stat, "value": value})

    @intent_handler(IntentBuilder("PokemonBaseSpeed").require("Speed")
                    .optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_speed(self, message):
        self.do_pokemon_base(message, "speed")

    @intent_handler(IntentBuilder("PokemonBaseSpecialDefense").require("Special").require("Defense")
                    .optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_special_defense(self, message):
        self.do_pokemon_base(message, "special-defense")

    @intent_handler(IntentBuilder("PokemonBaseSpecialAttack").require("Special").require("Attack")
                    .optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_special_attack(self, message):
        self.do_pokemon_base(message, "special-attack")

    @intent_handler(IntentBuilder("PokemonBaseDefense").require("Defense")
                    .optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_defense(self, message):
        self.do_pokemon_base(message, "defense")

    @intent_handler(IntentBuilder("PokemonBaseAttack").require("Attack")
                    .optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_attack(self, message):
        self.do_pokemon_base(message, "attack")

    @intent_handler(IntentBuilder("PokemonBaseHP").require("HP")
                    .optionally("Pokemon").optionally("Base"))
    def handle_pokemon_base_hp(self, message):
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
