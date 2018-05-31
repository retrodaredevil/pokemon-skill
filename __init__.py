import re
from difflib import SequenceMatcher
from math import floor

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

    error = str(stat_name) + " is an unsupported stat."
    LOG.error(error)
    raise ValueError(error)


def find_species_chain(chain, name_of_species):
    """
    NOTE: Each of the returned values may be NamedAPIResource objects or dicts, so make sure you use the attr method
    so it will do the work for you when you want attributes from them
    :param chain: The starting evolution chain
    :param name_of_species: The name of species you want the evolution chain for
    :return: A tuple where [0] is the evolution chain for the species before name_of_species or None if this is none,
             and [1] is the species chain for name_of_species
    """
    if attr(chain, "species.name") == name_of_species:
        return None, chain
    for evolution_chain in attr(chain, "evolves_to"):
        if attr(evolution_chain, "species.name") == name_of_species:
            return chain, evolution_chain
        r = find_species_chain(evolution_chain, name_of_species)
        if r:
            return r

    return None, None


def find_final_species_chains(chain):
    """
    :param chain: The evolution chain for a desired pokemon
    :return: A list of the possible final most evolutions related to chain.species. This could be empty
    """
    evolves_to = attr(chain, "evolves_to")
    if not evolves_to:
        return [chain]
    r = []
    for evolution_chain in evolves_to:
        r.extend(find_final_species_chains(evolution_chain))

    return r


def attr(obj, key):
    if isinstance(key, list):
        split = key
    else:
        split = key.split(".")
    key = split[0]
    if len(split) > 1:
        return attr(attr(obj, key), split[1:])
    if isinstance(obj, dict):
        return obj[key]
    return getattr(obj, key)


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
        return message.data.get("lang", None) or self.lang

    def _list_to_str(self, l):
        last = ""
        if len(l) >= 2:
            last = " " + self.translate("and") + " " + l[-1]
        return ", ".join(l[:-1]) + last

    def _use_english_units(self, message):
        # split = self._lang(message).split("-")
        # if len(split) >= 2:
        #     return split[1] == "us"
        # return False
        # docs on config: https://mycroft.ai/documentation/mycroft-conf/
        unit = self.config_core.get("system_unit")
        if unit != "english" and unit != "metric" and unit != "imperial":
            LOG.error("Unit is unknown. system_unit: " + str(unit))
        return unit == "english" or unit == "imperial"

    def _get_name_from_lang(self, names, lang=None):
        if not names:
            return None
        lang = (lang or "en-us").split("-")  # lang[0] is language, lang[1] is country
        lang_name = lang[0]
        country = len(lang) > 1 and lang[1] or ""  # use lang[1] as country or "" if lang doesn't have one

        best_name = None
        for name in names:
            language = name.language
            if language.name == lang_name:
                best_name = name.name
                if language.iso3166 == country or not country:
                    return best_name

        if not best_name:
            LOG.info("Couldn't find a name for lang: " + str(lang) + ", lang_name: " + lang_name +
                     ", country: " + country + " | using name: " + names[-1].name)

        return best_name or names[-1].name

    def _pokemon_name(self, mon, lang=None):
        """
        :param mon: The pokemon object created with the pokemon method
        :return: A more readable/friendly version of the pokemon's name
        """
        return self._get_name_from_lang(mon.forms[0].names, lang) or self._species_name(mon.species, lang)

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

    @intent_handler(IntentBuilder("PokemonIDIntent").require("ID"))
    def handle_pokemon_id(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        self.speak_dialog("pokemon.id.is", {"pokemon": self._pokemon_name(mon), "id": str(mon.species.id)})

    @intent_handler(IntentBuilder("PokemonWeightIntent").require("Weight"))
    def handle_pokemon_weight(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        kg = mon.weight / 10.0
        if self._use_english_units(message):
            display = str(int(round(kg * 2.20462))) + " " + self.translate("pounds")
        else:
            display = str(kg) + " " + self.translate("kilograms")

        self.speak_dialog("pokemon.weighs", {"pokemon": self._pokemon_name(mon), "weight": display})

    @intent_handler(IntentBuilder("PokemonHeightIntent").require("Height"))
    def handle_pokemon_height(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        meters = mon.height / 10.0
        if self._use_english_units(message):
            feet = meters * 3.28084
            whole_feet = floor(feet)
            inches = (feet - whole_feet) * 12
            display = str(whole_feet) + " " + self.translate("foot") +\
                " " + str(int(round(inches))) + " " + self.translate("inches")
        else:
            display = str(round(meters * 10.0) / 10.0) + " " + self.translate("meters")

        self.speak_dialog("pokemon.height", {"pokemon": self._pokemon_name(mon), "height": display})

    @intent_handler(IntentBuilder("PokemonTypeIntent").require("Type"))
    def handle_pokemon_type(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        types = mon.types

        pokemon_name = self._pokemon_name(mon, self._lang(message))
        if len(types) == 1:
            self.speak_dialog("pokemon.type.one", {"pokemon": pokemon_name, "type1": types[0].type.name})
        else:
            self.speak_dialog("pokemon.type.two", {"pokemon": pokemon_name, "type1": types[0].type.name,
                                                   "type2": types[1].type.name})

    @intent_handler(IntentBuilder("PokemonEvolveFinal").require("Evolve").require("final"))
    def handle_pokemon_evolve_final(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        lang = self._lang(message)
        pokemon_name = self._pokemon_name(mon, lang)

        species_chain = find_species_chain(mon.species.evolution_chain.chain, mon.species.name)[1]
        final_evolution_chain_list = find_final_species_chains(species_chain)
        if len(final_evolution_chain_list) == 1:
            evolution_chain = final_evolution_chain_list[0]
            if attr(evolution_chain, "species.name") == mon.species.name:  # pokemon is in final evolution
                if not mon.species.evolution_chain.chain.evolves_to:  # if evolves_to list is empty
                    self.speak_dialog("pokemon.has.no.evolutions", {"pokemon": pokemon_name})
                    return
                else:
                    self.speak_dialog("pokemon.is.in.final.evolution", {"pokemon": pokemon_name})
                    return
        elif len(final_evolution_chain_list) == 0:
            raise ValueError("find_final_species_chains() returned a list with a length of 0")

        names_list = []
        for evolution_chain in final_evolution_chain_list:
            name = self._species_name(pokemon_species(attr(evolution_chain, "species.name")), lang)
            names_list.append(name)
        display = self._list_to_str(names_list)
        if not display:
            LOG.error("display is empty. names_list: " + str(names_list) +
                      ", ...chain_list: " + str(final_evolution_chain_list))
        self.speak_dialog("pokemon.final.evolution", {"pokemon": pokemon_name,
                                                      "final": display})

    @intent_handler(IntentBuilder("PokemonEvolveFirst").require("Evolve").require("First"))
    def handle_pokemon_evolve_first(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        lang = self._lang(message)
        pokemon_name = self._pokemon_name(mon, lang)

        evolution_chain = mon.species.evolution_chain.chain
        species = evolution_chain.species
        if species.name == mon.species.name:  # mon is in first evolution
            if not evolution_chain.evolves_to:  # pokemon has no evolutions
                self.speak_dialog("pokemon.has.no.evolutions", {"pokemon": pokemon_name})
                return
            else:
                self.speak_dialog("pokemon.is.in.first.evolution", {"pokemon": pokemon_name})
                return
        species_name = self._species_name(species, lang)

        self.speak_dialog("pokemon.first.evolution.is", {"pokemon": pokemon_name, "first": species_name})

    @intent_handler(IntentBuilder("PokemonEvolveFromIntent").require("Evolve").require("From"))
    def handle_pokemon_evolve_from(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        lang = self._lang(message)
        previous_chain = find_species_chain(mon.species.evolution_chain.chain, mon.species.name)[0]
        pokemon_name = self._pokemon_name(mon, self._lang(message))
        if not previous_chain:
            self.speak_dialog("pokemon.has.no.previous.evolution", {"pokemon": pokemon_name})
            return
        species = pokemon_species(attr(previous_chain, "species.name"))
        species_name = self._species_name(species, lang)
        self.speak_dialog("pokemon.evolves.from", {"pokemon": pokemon_name, "from": species_name})

    @intent_handler(IntentBuilder("PokemonEvolveIntoIntent").require("Evolve").require("Into"))
    def handle_pokemon_evolve_into(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        lang = self._lang(message)

        into = attr(find_species_chain(mon.species.evolution_chain.chain, mon.species.name)[1], "evolves_to")
        names_into = []
        for evolution in into:
            names_into.append(str(self._species_name(
                pokemon_species(attr(evolution, "species.name")),
                lang
            )))

        pokemon_name = self._pokemon_name(mon, lang)
        if not names_into:
            self.speak_dialog("pokemon.does.not.evolve", {"pokemon": pokemon_name})
            return

        self.speak_dialog("pokemon.evolves.into", {"pokemon": pokemon_name,
                                                   "evolve": self._list_to_str(names_into),
                                                   "evolve_method": "method"})  # TODO

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

    @intent_handler(IntentBuilder("PokemonColor").require("Color"))
    def handle_pokemon_color(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        lang = self._lang(message)
        color_name = self._get_name_from_lang(mon.species.color.names, lang)
        pokemon_name = self._pokemon_name(mon, lang)

        self.speak_dialog("pokemon.color.is", {"pokemon": pokemon_name, "color": color_name})

    @intent_handler(IntentBuilder("PokemonShape").require("Shape"))
    def handle_pokemon_shape(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        lang = self._lang(message)
        shape_name = self._get_name_from_lang(mon.species.shape.names, lang)
        pokemon_name = self._pokemon_name(mon, lang)

        self.speak_dialog("pokemon.shape.is", {"pokemon": pokemon_name, "shape": shape_name})

    @intent_handler(IntentBuilder("PokemonHabitat").require("Habitat"))
    def handle_pokemon_habitat(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        lang = self._lang(message)
        habitat_name = self._get_name_from_lang(mon.species.habitat.names, lang)
        pokemon_name = self._pokemon_name(mon, lang)

        self.speak_dialog("pokemon.lives.in", {"pokemon": pokemon_name, "habitat": habitat_name})

    @intent_handler(IntentBuilder("PokemonBaseHappiness").require("Happiness").optionally("Base"))
    def handle_pokemon_base_happiness(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return
        lang = self._lang(message)
        pokemon_name = self._pokemon_name(mon, lang)
        happiness = mon.species.base_happiness
        self.speak_dialog("base.stat.is", {"pokemon": pokemon_name, "stat": "happiness", "value": str(happiness)})

    @intent_handler(IntentBuilder("PokemonBaseExperience").require("Experience").optionally("Base"))
    def handle_pokemon_base_experience(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return
        lang = self._lang(message)
        pokemon_name = self._pokemon_name(mon, lang)
        experience = mon.base_experience
        self.speak_dialog("base.stat.is", {"pokemon": pokemon_name, "stat": "experience", "value": str(experience)})

    @intent_handler(IntentBuilder("PokemonCaptureRate").require("CaptureRate"))
    def handle_pokemon_capture_rate(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return
        lang = self._lang(message)
        pokemon_name = self._pokemon_name(mon, lang)
        capture_rate = mon.species.capture_rate
        self.speak_dialog("pokemon.capture.rate", {"pokemon": pokemon_name, "rate": capture_rate})

    @intent_handler(IntentBuilder("PokemonEggGroups").require("Egg"))
    def handle_pokemon_egg_groups(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        lang = self._lang(message)

        groups = mon.species.egg_groups
        names_list = []
        for group in groups:
            group_name = self._get_name_from_lang(group.names, lang)
            names_list.append(group_name)

        display = self._list_to_str(names_list)
        if not display:
            LOG.error("display shouldn't be empty. groups: " + str(groups) + ", names_list: " + str(names_list))
        pokemon_name = self._pokemon_name(mon, lang)
        self.speak_dialog("pokemon.egg.groups.are", {"pokemon": pokemon_name, "groups": display})

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
