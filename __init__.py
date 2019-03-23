import re
from difflib import SequenceMatcher
from math import floor

from adapt.intent import IntentBuilder
from mycroft.skills.core import MycroftSkill, intent_handler
from mycroft.util.log import LOG
from pokebase import pokemon, APIResourceList, pokemon_species, evolution_trigger, item, type_, location


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
        self.pokemon_names = None
        self.last_pokemon = None

    def initialize(self):
        if not self.pokemon_names:
            self.pokemon_names = [name for name in APIResourceList("pokemon").names]
            # print("going to init names")
            # self.pokemon_names = [self._get_name_from_lang(mon.names) for mon in APIResourceList("pokemon")]
            # print("done")

    def _list_to_str(self, l, and_str=None):
        length = len(l)
        if length == 0:
            return ""
        elif length == 1:
            return l[0]
        if not and_str:
            and_str = self.translate("and")
        return ", ".join(l[:-1]) + " " + and_str + " " + l[-1]

    def _use_english_units(self, message):
        # docs on config: https://mycroft.ai/documentation/mycroft-conf/
        unit = self.config_core.get("system_unit")
        if unit != "english" and unit != "metric" and unit != "imperial":
            LOG.error("Unit is unknown. system_unit: " + str(unit))
        return unit == "english" or unit == "imperial"

    def _get_name_from_lang(self, names):
        if not names:
            return None
        lang = self.lang
        if isinstance(lang, str):
            lang = lang.split("-")
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
            trigger_name = "by " + trigger_name

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

        for name_element in self.pokemon_names:
            name_split = name_element.split("-")
            amount = .25 * sum(alike_amount(name) for name in name_split) + alike_amount(name_element)
            # amount = alike_amount(name_element)
            if amount > alike:
                name = name_element
                alike = amount

        LOG.info("name: " + name + " alike: " + str(alike))

        if not name or alike <= .3:
            return None
        try:
            return pokemon(name)
        except ValueError:
            LOG.error("Couldn't find pokemon with name: '" + str(name) + "' alike is: " + str(alike))
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

    @intent_handler(IntentBuilder("PokemonEvolveFinal").require("Evolve").require("Final"))
    def handle_pokemon_evolve_final(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

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

    @intent_handler(IntentBuilder("PokemonEvolveFirst").require("Evolve").require("First"))
    def handle_pokemon_evolve_first(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

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

    @intent_handler(IntentBuilder("PokemonEvolveFromIntent").require("Evolve").require("From"))
    def handle_pokemon_evolve_from(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

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

    @intent_handler(IntentBuilder("PokemonEvolveIntoIntent").require("Evolve").require("Into"))
    def handle_pokemon_evolve_into(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

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
            # LOG.info("species: " + species.name + ", _species_name(): " + name + " lang: " + lang)
            details_display = ""
            if should_add_details:
                evolution_details_list = attr(evolution, "evolution_details")
                evolution_details_str_list = []
                for evolution_details in evolution_details_list:
                    evolution_details_str_list.append(self._evolution_details_str(evolution_details))
                details_display = self._list_to_str(evolution_details_str_list, and_str=self.translate("or"))

            names_into.append(name + details_display)

        # LOG.info("names_into: " + str(names_into))
        if not names_into:
            self.speak_dialog("pokemon.does.not.evolve", {"pokemon": pokemon_name})
            return

        display = self._list_to_str(names_into, and_str=self.translate(". or ."))

        self.speak_dialog("pokemon.evolves.into", {"pokemon": pokemon_name,
                                                   "evolve": display})

    @intent_handler(IntentBuilder("PokemonFormIntent").require("Form"))
    def handle_pokemon_form(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

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
        version_names = [self._get_name_from_lang(version.names) for version in versions]
        self.speak_dialog("pokemon.version.introduced", {
            "pokemon": self._pokemon_name(mon),
            "versions": self._list_to_str(version_names),
            "generation": version_group.generation.id
        })

    @intent_handler(IntentBuilder("PokemonGenerationIntroduced").require("Game").require("Introduced"))
    def handle_generation_introduced(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return
        self.do_pokemon_version_introduced(mon)

    def do_pokemon_base(self, message, stat):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        value = base_stat(mon, stat)
        self.speak_dialog("base.stat.is", {"pokemon": self._pokemon_name(mon),
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

        color_name = self._get_name_from_lang(mon.species.color.names)
        pokemon_name = self._pokemon_name(mon)

        self.speak_dialog("pokemon.color.is", {"pokemon": pokemon_name, "color": color_name})

    @intent_handler(IntentBuilder("PokemonShape").require("Shape"))
    def handle_pokemon_shape(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        shape_name = self._get_name_from_lang(mon.species.shape.names)
        pokemon_name = self._pokemon_name(mon)

        self.speak_dialog("pokemon.shape.is", {"pokemon": pokemon_name, "shape": shape_name})

    @intent_handler(IntentBuilder("PokemonHabitat").require("Habitat"))
    def handle_pokemon_habitat(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        habitat_name = self._get_name_from_lang(mon.species.habitat.names)
        pokemon_name = self._pokemon_name(mon)

        self.speak_dialog("pokemon.lives.in", {"pokemon": pokemon_name, "habitat": habitat_name})

    @intent_handler(IntentBuilder("PokemonBaseHappiness").require("Happiness").optionally("Base"))
    def handle_pokemon_base_happiness(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return
        pokemon_name = self._pokemon_name(mon)
        happiness = mon.species.base_happiness
        self.speak_dialog("base.stat.is", {"pokemon": pokemon_name, "stat": "happiness", "value": str(happiness)})

    @intent_handler(IntentBuilder("PokemonBaseExperience").require("Experience").optionally("Base"))
    def handle_pokemon_base_experience(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return
        pokemon_name = self._pokemon_name(mon)
        experience = mon.base_experience
        self.speak_dialog("base.stat.is", {"pokemon": pokemon_name, "stat": "experience", "value": str(experience)})

    @intent_handler(IntentBuilder("PokemonCaptureRate").require("CaptureRate"))
    def handle_pokemon_capture_rate(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return
        pokemon_name = self._pokemon_name(mon)
        capture_rate = mon.species.capture_rate
        self.speak_dialog("pokemon.capture.rate", {"pokemon": pokemon_name, "rate": capture_rate})

    @intent_handler(IntentBuilder("PokemonEggGroups").require("Egg"))
    def handle_pokemon_egg_groups(self, message):
        mon = self._extract_pokemon(message)
        mon = self._check_pokemon(mon)
        if not mon:
            return

        groups = mon.species.egg_groups
        names_list = []
        for group in groups:
            group_name = self._get_name_from_lang(group.names)
            names_list.append(group_name)

        display = self._list_to_str(names_list)
        pokemon_name = self._pokemon_name(mon)
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
