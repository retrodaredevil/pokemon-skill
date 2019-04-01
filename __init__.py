import re
from difflib import SequenceMatcher
from math import ceil

from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill, intent_handler
from mycroft.skills.common_query_skill import CommonQuerySkill, CQSMatchLevel
from mycroft.util.log import LOG
from pokebase import pokemon, APIResourceList, pokemon_species, evolution_trigger, item, type_, location, ability, \
    version


__author__ = "retrodaredevil"


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
        if r[0] and r[1]:
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
    """
    A simple method to get the attribute of an object or a dictionary. This avoids complex statements like:

    `obj.something.another_thing["something"].another_thing["more"]`

    to just

    `attr(obj, "something.another_thing.something.another_thing.more")`

    :param obj: The object or dictionary to get an attribute from
    :param key: The attribute key such as "something.something"
    :return: The attribute
    """
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
    return re.split(r"\W+", to_split)


# useful docs: https://mycroft-core.readthedocs.io/en/stable/source/mycroft.html#mycroftskill-class
# Even more useful docs: https://pokeapi.co/docs/v2.html/
class PokemonSkill(CommonQuerySkill):  # TODO Use CommonQuerySkill

    def __init__(self):
        super(PokemonSkill, self).__init__(name="Pokemon")
        self.pokemon_names = None
        """A list of strings representing all pokemon names. These are always in english and are not 
        display-friendly. e.g.: rattata-alola"""
        self.type_names = None
        """A list of strings representing all type names. These are in english and are not display-friendly"""
        self.version_names = None
        """A list of strings representing all version names. These are in english and are not display-friendly"""
        self.ability_names = None
        """A list of strings representing all ability names. These are in english and are not display-friendly"""
        self.last_pokemon = None
        """The last referenced Pokemon. Should only be used by _check_pokemon"""
        self.last_ability = None
        """The last referenced Ability. Should only be used by _check_ability"""
        self.last_generation = None
        """An int representing the last generation referenced. Not currently used"""

    def initialize(self):
        if not self.pokemon_names:
            self.pokemon_names = list(APIResourceList("pokemon").names)
        if not self.type_names:
            self.type_names = list(APIResourceList("type").names)
        if not self.version_names:
            self.version_names = list(APIResourceList("version").names)
        if not self.ability_names:
            self.ability_names = list(APIResourceList("ability").names)

    def _list_to_str(self, l, and_str=None):
        """Converts a list to a string"""
        length = len(l)
        if length == 0:
            return ""
        elif length == 1:
            return l[0]
        if not and_str:
            and_str = self.translate("and")
        return ", ".join(l[:-1]) + ", " + and_str + ". " + l[-1]

    def _use_english_units(self, phrase):
        """
        :param message: The message object
        :return: True to use English units, False otherwise
        """
        # docs on config: https://mycroft.ai/documentation/mycroft-conf/
        if self.voc_match(phrase, "EnglishWeight") or self.voc_match(phrase, "EnglishLength"):
            return True
        if self.voc_match(phrase, "MetricWeight") or self.voc_match(phrase, "MetricLength"):
            return False

        unit = self.config_core.get("system_unit")
        if unit != "english" and unit != "metric" and unit != "imperial":
            LOG.error("Unit is unknown. system_unit: " + str(unit))
        return unit == "english" or unit == "imperial"

    def _get_lang(self):
        """
        :return: A tuple where [0] is the language name code and [1] is the country. [1] may be an empty string
        """
        lang = self.lang
        if isinstance(lang, str):
            lang = lang.split("-")
        lang_name = lang[0]
        country = len(lang) > 1 and lang[1] or ""  # use lang[1] as country or "" if lang doesn't have one
        return lang_name, country

    def _get_name_from_lang(self, names):
        if not names:
            return None
        lang_name, country = self._get_lang()

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

    def _pokemon_name(self, mon):
        """
        :param mon: The pokemon object created with the pokemon method
        :return: A more readable/friendly version of the pokemon's name
        """
        return self._get_name_from_lang(mon.forms[0].names) or self._species_name(mon.species)

    def _species_name(self, species):
        return self._get_name_from_lang(species.names) or species.name

    def _form_name(self, mon):
        """
        :param mon: The pokemon object created with the pokemon method
        :return: A readable/friendly version of the pokemon's form or None if the pokemon isn't in a form
        """
        forms = mon.forms
        if not forms:
            return None  # this could happen in the future, but this shouldn't happen as of right now
        form = forms[0]
        return self._get_name_from_lang(form.form_names) or None

    def _evolution_details_str(self, evolution_details):
        """

        :param evolution_details: Usually a dict
        :return: A string representing events needed to happen to evolve based on evolution_details
        """
        # ==== variables ====
        trigger = evolution_trigger(evolution_details["trigger"]["name"])
        trigger_name = self._get_name_from_lang(trigger.names)
        if trigger_name:
            trigger_name = " by " + trigger_name

        held_item = evolution_details["held_item"]
        held_item_display = ""
        if held_item:
            held_item_display = " by holding " + self._get_name_from_lang(item(held_item["name"]).names)

        min_level = evolution_details["min_level"]  # None or min level
        min_level_display = ""
        if min_level:
            min_level_display = " at level " + str(min_level)

        min_happiness = evolution_details["min_happiness"]  # None or min happiness
        min_happiness_display = ""
        if min_happiness:
            min_happiness_display = " with happiness " + str(min_happiness)

        min_beauty = evolution_details["min_beauty"]
        min_beauty_display = ""
        if min_beauty:
            min_beauty_display = " with beauty level " + str(min_beauty)

        min_affection = evolution_details["min_affection"]
        min_affection_display = ""
        if min_affection:
            min_affection_display = " with affection level " + str(min_affection)

        time_of_day = evolution_details["time_of_day"]  # None or "day" or "night"
        time_display = ""
        if time_of_day:
            time_display = " at " + time_of_day

        gender = evolution_details["gender"]  # None, 1=female, 2=male
        gender_display = ""
        if gender:
            gender_display = " if " + ("female" if gender == 1 else "male")

        party_type_dict = evolution_details["party_type"]
        party_type_display = ""  # must have this type of pokemon in their party
        if party_type_dict:
            party_type = type_(party_type_dict["name"])
            party_type_display = " with " + self._get_name_from_lang(party_type.names) + " type pokemon in party"

        location_dict = evolution_details["location"]
        location_display = ""
        if location_dict:
            game_location = location(location_dict["name"])
            location_display = " at " + self._get_name_from_lang(game_location.names)

        needs_rain_display = ""
        if evolution_details["needs_overworld_rain"]:
            needs_rain_display = " while it's raining"

        # TODO known_move and known_move_type and party_type and turn_upside_down and translate everything

        # ==== different triggers ====
        if trigger.name == "shed":
            return trigger_name
        elif trigger.name == "use-item":
            used_item = item(evolution_details["item"]["name"])
            return trigger_name + " " + self._get_name_from_lang(used_item.names)
        elif trigger.name == "trade":
            trade_species_dict = evolution_details["trade_species"]
            trade_species_display = ""
            if trade_species_dict:
                trade_species = pokemon_species(trade_species_dict["name"])
                trade_species_display = " for " + self._get_name_from_lang(trade_species.names)  # TODO translate
            return trigger_name + held_item_display + trade_species_display

        # === level up trigger below ===
        level_up_display = trigger_name
        if min_level_display:
            level_up_display = min_level_display

        return level_up_display + held_item_display + min_happiness_display + min_beauty_display \
            + min_affection_display + time_display + location_display + needs_rain_display + gender_display \
            + party_type_display

    @staticmethod
    def _extract_name(message, names):
        """
        Gets the string that appeared most accurately in message.
        :param message: The message object or str
        :param names: A list of strings
        :return: One of the elements in names or None.
        """
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

        if isinstance(message, str):
            utt = message
        else:
            utt = message.data["utterance"]
        split = split_word(utt)

        name = None
        alike = 0

        for name_element in names:
            name_split = name_element.split("-")
            amount = .25 * sum(alike_amount(name) for name in name_split) + alike_amount(name_element)
            # amount = alike_amount(name_element)
            if amount > alike:
                name = name_element
                alike = amount

        if not name or alike <= 1.0:
            return None
        return name

    def _extract_pokemon(self, message):
        name = self.__class__._extract_name(message, self.pokemon_names)
        if not name:
            return None
        try:
            return pokemon(name)
        except ValueError:
            LOG.error("Couldn't find pokemon with name: '" + str(name))
            raise

    def _extract_type(self, message):
        name = self.__class__._extract_name(message, self.type_names)
        if not name:
            return None
        try:
            return type_(name)
        except ValueError:
            LOG.error("Couldn't find type with name: '" + str(name))
            raise

    def _extract_ability(self, message):
        name = self.__class__._extract_name(message, self.ability_names)
        if not name:
            return None
        try:
            return ability(name)
        except ValueError:
            LOG.error("Couldn't find ability with name: '" + str(name))
            raise

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

    def _check_ability(self, abil):
        if not abil:
            if not self.last_ability:
                self.speak_dialog("unable.to.find.ability")
                return None
            else:
                abil = self.last_ability
        self.last_ability = abil
        return abil

    def CQS_match_query_phrase(self, phrase):
        LOG.info("querying in Pokemon!!!")
        mon = self._extract_pokemon(phrase)
        LOG.info("Should be returning!!!")
        if mon:
            return phrase, CQSMatchLevel.EXACT, True, ("pokemon", mon.name)
        if self.voc_match(phrase, "Pokemon") and self.last_pokemon:
            return phrase, CQSMatchLevel.EXACT, ("pokemon", None)
        elif self.voc_match(phrase, "Evolve"):
            return phrase, CQSMatchLevel.CATEGORY, True, ("pokemon", None)
        elif any(self.voc_match(phrase, vocab) for vocab in ["Height", "Weight", "Type", "Form"]):
            return phrase, CQSMatchLevel.GENERAL, True, ("pokemon", None)

        abil = self._extract_ability(phrase)
        if abil:
            return phrase, CQSMatchLevel.CATEGORY, True, ("ability", abil.name)

        return None

    def CQS_action(self, phrase, data):
        data_type = data[0]  # a string
        data_name = data[1]  # The resource or None

        if data_type == "pokemon":
            mon = self._check_pokemon(pokemon(data_name) if data_name else None)
            if not mon:
                return

            if self.voc_match(phrase, "Evolve"):
                if self.voc_match(phrase, "Final"):
                    self.do_pokemon_evolve_final(mon)
                elif self.voc_match(phrase, "First"):
                    self.do_pokemon_evolve_first(mon)
                elif self.voc_match(phrase, "From"):
                    self.do_pokemon_evolve_previous(mon)
                else:
                    self.do_pokemon_evolve_into(mon)
            elif self.voc_match(phrase, "Ability"):
                self.do_pokemon_abilities(mon)
            elif self.voc_match(phrase, "Introduced"):
                self.do_pokemon_version_introduced(mon)
            elif self.voc_match(phrase, "Effective") and self.voc_match(phrase, "Against"):
                self.do_type_effectiveness(mon, phrase)
            elif self.voc_match(phrase, "Weight"):
                self.do_pokemon_weight(mon, phrase)
            elif self.voc_match(phrase, "Height"):
                self.do_pokemon_height(mon, phrase)
            elif self.voc_match(phrase, "Type"):
                self.do_pokemon_type(mon)
            elif self.voc_match(phrase, "Form"):
                self.do_pokemon_form(mon)
            elif self.voc_match(phrase, "ID"):
                self.speak_dialog("pokemon.id.is", {"pokemon": self._pokemon_name(mon), "id": str(mon.species.id)})
            elif self.voc_match(phrase, "Speed"):
                self.do_pokemon_base(mon, "speed")
            elif self.voc_match(phrase, "HP"):
                self.do_pokemon_base(mon, "hp")
            elif self.voc_match(phrase, "Color"):
                self.do_pokemon_color(mon)
            elif self.voc_match(phrase, "Shape"):
                self.do_pokemon_shape(mon)
            elif self.voc_match(phrase, "Habitat"):
                self.do_pokemon_habitat(mon)
            elif self.voc_match(phrase, "Happiness"):
                self.do_pokemon_base_happiness(mon)
            elif self.voc_match(phrase, "Experience"):
                self.do_pokemon_base_experience(mon)
            elif self.voc_match(phrase, "Egg"):
                self.do_pokemon_egg_groups(mon)
            elif self.voc_match(phrase, "CaptureRate"):
                self.do_pokemon_capture_rate(mon)
            else:
                attack = self.voc_match(phrase, "Attack")
                defense = self.voc_match(phrase, "Defense")
                special = self.voc_match(phrase, "Special")
                if attack or defense or special:
                    if special:
                        if defense:
                            self.do_pokemon_base(mon, "special-defense")
                        else:
                            self.do_pokemon_base(mon, "special-attack")
                    else:
                        if attack:
                            self.do_pokemon_base(mon, "attack")
                        else:
                            assert defense
                            self.do_pokemon_base(mon, "defense")
                else:
                    self.speak_dialog("cannot.answer.about.pokemon")
        elif data_type == "ability":
            if data_name:
                abil = ability(data_name)
                if self.voc_match(phrase, "AbilityFlavorText"):
                    self.do_ability_flavor_text(abil, phrase)
                elif self.voc_match(phrase, "Introduced"):
                    self.do_ability_generation_introduced(abil)
                elif self.voc_match(phrase, "AbilityEffectEntry"):
                    self.do_ability_effect_entry(abil, short=False)
                else:
                    self.do_ability_effect_entry(abil, short=True)
            else:
                self.speak_dialog("cannot.answer.about.ability")

    def do_pokemon_weight(self, mon, phrase):
        kg = mon.weight / 10.0
        if self._use_english_units(phrase):
            display = str(int(round(kg * 2.20462))) + " " + self.translate("pounds")
        else:
            display = str(kg) + " " + self.translate("kilograms")

        self.speak_dialog("pokemon.weighs", {"pokemon": self._pokemon_name(mon), "weight": display})

    def do_pokemon_height(self, mon, phrase):
        meters = mon.height / 10.0
        if self._use_english_units(phrase):
            feet = meters * 3.28084
            total_inches = int(round(feet * 12))
            whole_feet, inches = divmod(total_inches, 12)
            if whole_feet > 0:
                if inches > 0:
                    display = str(whole_feet) + " " + self.translate("foot") +\
                        " " + str(inches) + " " + self.translate("inches")
                else:
                    display = str(whole_feet) + " " + self.translate("foot")
            else:
                display = str(inches) + " " + self.translate("inches")
        else:
            display = str(round(meters * 10.0) / 10.0) + " " + self.translate("meters")

        self.speak_dialog("pokemon.height", {"pokemon": self._pokemon_name(mon), "height": display})

    def do_pokemon_type(self, mon):
        names = []
        for type_slot in sorted(mon.types, key=lambda x: x.slot):
            pokemon_type = type_slot.type
            names.append(self._get_name_from_lang(pokemon_type.names))

        pokemon_name = self._pokemon_name(mon)
        if len(names) == 1:
            self.speak_dialog("pokemon.type.one", {"pokemon": pokemon_name, "type1": names[0]})
        else:
            self.speak_dialog("pokemon.type.two", {"pokemon": pokemon_name, "type1": names[0],
                                                   "type2": names[1]})
            if len(names) > 2:
                LOG.info("This pokemon has more than two types??? names: " + str(names) + " pokemon: " + pokemon_name)

    # region evolution
    def do_pokemon_evolve_final(self, mon):
        pokemon_name = self._pokemon_name(mon)

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
            name = self._species_name(pokemon_species(attr(evolution_chain, "species.name")))
            names_list.append(name)
        display = self._list_to_str(names_list)
        if not display:
            LOG.error("display is empty. names_list: " + str(names_list) +
                      ", ...chain_list: " + str(final_evolution_chain_list))
        self.speak_dialog("pokemon.final.evolution", {"pokemon": pokemon_name,
                                                      "final": display})

    def do_pokemon_evolve_first(self, mon):
        pokemon_name = self._pokemon_name(mon)

        evolution_chain = mon.species.evolution_chain.chain
        species = evolution_chain.species
        if species.name == mon.species.name:  # mon is in first evolution
            if not evolution_chain.evolves_to:  # pokemon has no evolutions
                self.speak_dialog("pokemon.has.no.evolutions", {"pokemon": pokemon_name})
                return
            else:
                self.speak_dialog("pokemon.is.in.first.evolution", {"pokemon": pokemon_name})
                return
        species_name = self._species_name(species)

        self.speak_dialog("pokemon.first.evolution.is", {"pokemon": pokemon_name, "first": species_name})

    def do_pokemon_evolve_previous(self, mon):
        previous_chain = find_species_chain(mon.species.evolution_chain.chain, mon.species.name)[0]
        how = ""
        for evolution in attr(previous_chain, "evolves_to"):
            if attr(evolution, "species.name") == mon.species.name:
                details_list = attr(evolution, "evolution_details")
                how_str_list = []
                for details in details_list:
                    how_str_list.append(self._evolution_details_str(details))
                how = self._list_to_str(how_str_list)
                break
        previous_species = mon.species.evolves_from_species
        pokemon_name = self._pokemon_name(mon)
        if not previous_species:
            self.speak_dialog("pokemon.has.no.previous.evolution", {"pokemon": pokemon_name})
            return
        species_name = self._species_name(previous_species)
        self.speak_dialog("pokemon.evolves.from", {"pokemon": pokemon_name, "from": species_name, "how": how})

    def do_pokemon_evolve_into(self, mon):
        pokemon_name = self._pokemon_name(mon)

        species_chain = find_species_chain(mon.species.evolution_chain.chain, mon.species.name)[1]
        if not species_chain:
            self.speak_dialog("pokemon.does.not.evolve", {"pokemon": pokemon_name})
            return

        into = attr(species_chain, "evolves_to")
        should_add_details = len(into) <= 2
        names_into = []
        for evolution in into:
            species = pokemon_species(attr(evolution, "species.name"))
            name = self._species_name(species)
            details_display = ""
            if should_add_details:
                evolution_details_list = attr(evolution, "evolution_details")
                evolution_details_str_list = []
                for evolution_details in evolution_details_list:
                    evolution_details_str_list.append(self._evolution_details_str(evolution_details))
                details_display = self._list_to_str(evolution_details_str_list, and_str=self.translate("or"))

            names_into.append(name + details_display)

        if not names_into:
            self.speak_dialog("pokemon.does.not.evolve", {"pokemon": pokemon_name})
            return

        display = self._list_to_str(names_into, and_str=self.translate(". or ."))

        self.speak_dialog("pokemon.evolves.into", {"pokemon": pokemon_name,
                                                   "evolve": display})

    # endregion

    def do_pokemon_form(self, mon):
        pokemon_name = self._pokemon_name(mon)
        form_name = self._form_name(mon)
        if not form_name:
            self.speak_dialog("pokemon.has.no.forms", {"pokemon": pokemon_name})
            return

        self.speak_dialog("pokemon.is.in.form", {"pokemon": pokemon_name, "form": form_name})

    def do_pokemon_version_introduced(self, mon):
        forms = mon.forms
        if not forms:
            raise Exception("mon.forms is None or empty! forms: " + str(forms))
        version_group = forms[0].version_group
        versions = version_group.versions
        version_names = [self._get_name_from_lang(v.names) for v in versions]
        generation_id = version_group.generation.id
        self.last_generation = generation_id
        self.speak_dialog("pokemon.version.introduced", {
            "pokemon": self._pokemon_name(mon),
            "versions": self._list_to_str(version_names),
            "generation": generation_id
        })

    def do_ability_generation_introduced(self, abil):
        generation_id = abil.generation.id
        self.last_generation = generation_id
        name = self._get_name_from_lang(abil.names)
        self.speak_dialog("ability.generation.introduced", {"ability": name, "generation": generation_id})


    # region simple stats
    def do_pokemon_base(self, mon, stat):
        value = base_stat(mon, stat)
        self.speak_dialog("base.stat.is", {"pokemon": self._pokemon_name(mon),
                                           "stat": stat, "value": value})

    def do_pokemon_color(self, mon):
        color_name = self._get_name_from_lang(mon.species.color.names)
        pokemon_name = self._pokemon_name(mon)

        self.speak_dialog("pokemon.color.is", {"pokemon": pokemon_name, "color": color_name})

    def do_pokemon_shape(self, mon):
        shape_name = self._get_name_from_lang(mon.species.shape.names)
        pokemon_name = self._pokemon_name(mon)

        self.speak_dialog("pokemon.shape.is", {"pokemon": pokemon_name, "shape": shape_name})

    def do_pokemon_habitat(self, mon):
        habitat_name = self._get_name_from_lang(mon.species.habitat.names)
        pokemon_name = self._pokemon_name(mon)

        self.speak_dialog("pokemon.lives.in", {"pokemon": pokemon_name, "habitat": habitat_name})

    def do_pokemon_base_happiness(self, mon):
        pokemon_name = self._pokemon_name(mon)
        happiness = mon.species.base_happiness
        self.speak_dialog("base.stat.is", {"pokemon": pokemon_name, "stat": "happiness", "value": str(happiness)})

    def do_pokemon_base_experience(self, mon):
        pokemon_name = self._pokemon_name(mon)
        experience = mon.base_experience
        self.speak_dialog("base.stat.is", {"pokemon": pokemon_name, "stat": "experience", "value": str(experience)})

    def do_pokemon_capture_rate(self, mon):
        pokemon_name = self._pokemon_name(mon)
        capture_rate = mon.species.capture_rate
        self.speak_dialog("pokemon.capture.rate", {"pokemon": pokemon_name, "rate": capture_rate})

    def do_pokemon_egg_groups(self, mon):
        groups = mon.species.egg_groups
        names_list = []
        for group in groups:
            group_name = self._get_name_from_lang(group.names)
            names_list.append(group_name)

        display = self._list_to_str(names_list)
        pokemon_name = self._pokemon_name(mon)
        self.speak_dialog("pokemon.egg.groups.are", {"pokemon": pokemon_name, "groups": display})

    # endregion

    def do_type_effectiveness(self, mon, phrase):

        desired_type = self._extract_type(phrase)
        if not desired_type:
            self.speak_dialog("no.type.specified")
            return
        type_name = desired_type.name

        effectiveness = 0
        for type_slot in sorted(mon.types, key=lambda x: x.slot):
            pokemon_type = type_slot.type
            damage = pokemon_type.damage_relations
            if type_name in (t["name"] for t in damage.no_damage_from):
                effectiveness = None
                break
            elif type_name in (t["name"] for t in damage.double_damage_from):
                effectiveness += 1
            elif type_name in (t["name"] for t in damage.half_damage_from):
                effectiveness -= 1

        speak_dict = {
            "type": self._get_name_from_lang(type_(type_name).names),
            "pokemon": self._pokemon_name(mon)
        }
        if effectiveness is None:
            self.speak_dialog("type.is.none", speak_dict)
        elif effectiveness == 0:
            self.speak_dialog("type.is.normal", speak_dict)
        elif effectiveness < 0:
            self.speak_dialog("type.is.half", speak_dict)
        else:
            self.speak_dialog("type.is.super", speak_dict)

    def do_pokemon_abilities(self, mon):
        normal_abilities = []
        hidden_abilities = []
        for abil in sorted(mon.abilities, key=lambda x: x.slot):
            name = self._get_name_from_lang(abil.ability.names)
            if abil.is_hidden:
                hidden_abilities.append(name)
            else:
                normal_abilities.append(name)

        pokemon_name = self._pokemon_name(mon)

        if not normal_abilities and not hidden_abilities:
            self.speak_dialog("pokemon.abilities.none")
        elif not normal_abilities:  # only hidden
            self.speak_dialog("pokemon.abilities.hidden", {"pokemon": pokemon_name,
                                                           "hidden_abilities": self._list_to_str(hidden_abilities)})
        elif not hidden_abilities:
            self.speak_dialog("pokemon.abilities.non-hidden", {"pokemon": pokemon_name,
                                                               "abilities": self._list_to_str(normal_abilities)})
        else:  # has both
            self.speak_dialog("pokemon.abilities.hidden.non-hidden", {
                "pokemon": pokemon_name,
                "abilities": self._list_to_str(normal_abilities),
                "hidden_abilities": self._list_to_str(hidden_abilities)
            })

    def do_ability_flavor_text(self, abil, phrase):
        version_name = self.__class__._extract_name(phrase, self.version_names)
        lang_name = self._get_lang()[0]
        text = None
        for flavor_text in abil.flavor_text_entries:
            is_lang_correct = flavor_text.language.name == lang_name
            if is_lang_correct or not text:
                if not version_name or any(v.name == version_name for v in flavor_text.version_group.versions):
                    text = flavor_text.flavor_text
                    if is_lang_correct:
                        break
        if text:
            self.speak_dialog("ability.flavor.text", {"ability": self._get_name_from_lang(abil.names),
                                                      "info": text})
        else:
            ability_version = version(version_name)
            self.speak_dialog("ability.not.in.version",
                              {"ability": self._get_name_from_lang(abil.names),
                               "version": self._get_name_from_lang(ability_version.names)})

    def do_ability_effect_entry(self, abil, short=True):
        key = "short_effect" if short else "effect"
        text = None
        lang_name = self._get_lang()[0]
        for effect_entry in abil.effect_entries:
            is_correct_lang = effect_entry.language.name == lang_name
            if is_correct_lang or not text:
                text = attr(effect_entry, key)
                if is_correct_lang:
                    break
        if not text:
            raise Exception("The ability didn't have effect_entries? ability.effect_entries: "
                            + str(abil.effect_entries))
        self.speak_dialog("ability.effect.entry", {"ability": self._get_name_from_lang(abil.names),
                                                   "info": text})


def create_skill():
    return PokemonSkill()
