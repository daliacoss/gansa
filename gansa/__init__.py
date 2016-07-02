#!/usr/bin/env python

# This file is part of Gansa.

# Gansa is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Gansa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Gansa.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function
import sys, os, collections, shutil, csv, functools, copy, importlib, codecs
import jinja2, markdown, yaml, sqlalchemy, sqlalchemy.orm, mongoengine, six
from markdown.extensions.meta import MetaExtension

TMP_TEMPLATE = """
{{% extends '{0}' %}}
{{% block {1} %}}
{2}
{{% endblock %}}
"""

SUPPORTED_DB_ENGINES = {"yaml", "sqlite", "postgresql", "mysql", "csv", "mongodb"}

def _deep_update(dict1, dict2):
	for k, v in dict2.items():
		if isinstance(v, collections.Mapping):
			r = _deep_update(dict1.get(k, {}), v)
			dict1[k] = r
		else:
			dict1[k] = v
	return dict1

def _tonumber(s):
	try:
		return int(s)
	except ValueError:
		return float(s)

def _collection(item):
	if not isinstance(item, collections.Iterable) or isinstance(item, six.string_types):
		item = [item]
	return item

def _eval_module_and_object(s):

	module_name, variable_name = s.split(":")

	# module = imp.load_source("context_processor", os.path.join(self.environment_src, module_name))
	module = importlib.import_module(module_name)
	variable_name_list = variable_name.split(".")
	o = module

	for v in variable_name_list:
		o = getattr(o, v)

	return module, o

def _path_splitall(path):

	folders = []

	while path:
		path, folder = os.path.split(path)
		if folder:
			folders.append(folder)

	folders.reverse()
	return folders

class Site(object):

	default_settings = {
		"environment": {
			"views": "views.yaml",
			"pages": "pages",
			"templates": "templates",
			"assets": "assets",
			"user": "user.yaml"
		},
		"pages": {
			"extensions": [],
			"extension_options": {},
		},
		"templates": {
			"default_block": "content",
			"builtins": []
		},
		"callbacks": {
			"postrender": ""
		}
	}

	default_user_settings = {
		"database": {}
	}

	def __init__(self, environment, load=True):

		self.environment = os.path.abspath(environment)
		self.settings = copy.deepcopy(self.default_settings)
		self.user_settings = copy.deepcopy(self.default_user_settings)
		self.views = []
		self.db = {}

		if not load or not os.path.exists(self.environment_src):
			return

		self.load_environment()

		sys.path.append(self.environment_src)

	def load_environment(self):

		self.load_settings()
		self.load_user_settings()
		self.load_templates()
		self.load_views()
		self.load_db()

	def load_db(self):

		db_engine = self.user_settings["database"].get("engine")
		if not db_engine:
			return

		if db_engine == "yaml":
			with open(os.path.join(self.environment_src, self.user_settings["database"]["uri"])) as stream:
				self.db = yaml.load(stream) or {}
		elif db_engine == "csv":
			db_fnames = _collection(self.user_settings["database"]["uri"])

			store_row_as = self.user_settings["database"].get("store_row_as", "array")
			self.db = {}

			for fname in db_fnames:
				with open(os.path.join(self.environment_src, fname)) as stream:
					table_name = ".".join(fname.split(".")[:-1])
					if store_row_as == "dict":
						self.db[table_name] = [row for row in csv.DictReader(stream)]
					elif store_row_as == "array":
						self.db[table_name] = [row for row in csv.reader(stream)]
					else:
						raise ValueError("{0} is not a recognized csv storage format".format(store_row_as))

					if self.user_settings["database"].get("convert_numbers_and_bools", True):
						for row in self.db[table_name]:
							if store_row_as == "dict":
								for k, v in row.items():
									try:
										row[k] = _tonumber(v)
									except:
										row[k] = {"true":True, "false":False}.get(row[k], row[k])
							if store_row_as == "array":
								for i, v in enumerate(row):
									try:
										row[i] = _tonumber(v)
									except:
										row[i] = {"true":True, "false":False}.get(row[i], row[i])
		elif db_engine in ["sqlite", "postgresql", "mysql"]:
			if db_engine == "sqlite":
				uri = self.user_settings["database"]["uri"]
				p = uri.split("sqlite:///")[1]

				if p and not os.path.isabs(p):
					uri = "sqlite:///" + os.path.join(self.environment_src, p)
				self.db_engine = sqlalchemy.create_engine(uri)

			else:
				self.db_engine = sqlalchemy.create_engine(self.user_settings["database"]["uri"])

			self.db = sqlalchemy.orm.sessionmaker(bind=self.db_engine)()
		elif db_engine == "mongodb":
			self.db = mongoengine.connect(host=self.user_settings["database"]["uri"])

	def load_templates(self):

		template_loader = jinja2.FileSystemLoader(os.path.join(self.environment_src, self.settings["environment"]["templates"]))
		self.templates = jinja2.Environment(cache_size=0, loader=template_loader, extensions=['pyjade.ext.jinja.PyJadeExtension'])

	def load_views(self):

		with open(os.path.join(self.environment_src, self.settings["environment"]["views"])) as vstream:
			self.views = yaml.load(vstream) or []
		self.set_view_full_routes()

		self.set_view_parameter(self.views, "template", default_value="")
		self.set_view_parameter(self.views, "context", default_value={})
		self.set_view_parameter(self.views, "context_processor", default_value="")
		self.set_view_parameter(self.views, "pages", default_value=None)

	def load_settings(self, merge=True):
		"""
		load settings from this project's settings.yaml file

		parameters:
			merge=True: attempt to merge settings with already loaded settings
		"""

		with open(os.path.join(self.environment_src, "settings.yaml")) as settings_file:
			settings = yaml.load(settings_file)
			_deep_update(self.settings, settings)

	def load_user_settings(self):

		if not self.settings["environment"]["user"]:
			return

		with open(os.path.join(self.environment_src, self.settings["environment"]["user"])) as settings_file:
			self.user_settings = yaml.load(settings_file)

		db = self.user_settings["database"].get("uri")

		if not db:
			return

		if isinstance(db, list):
			fname = db[0]
		else:
			fname = db


		# attempt to infer db engine from file name, if one is not specified

		engine = self.user_settings["database"].get("engine")

		if not engine:
			for pair in [
				("sqlite://","sqlite"),
				("postgresql://","postgresql"),
				("mysql://","mysql"),
				("mongodb://","mongodb")
			]:
				if fname.startswith(pair[0]):
					engine = pair[1]
					break
			else:
				engine = {
					"yaml": "yaml",
					"csv": "csv",
					"sqlite": "sqlite",
					"db": "sqlite"
				}.get(fname.split(".")[-1])

		if not engine:
			raise ValueError("could not infer database engine")
		elif engine not in SUPPORTED_DB_ENGINES:
			raise ValueError("{0} is not a supported database engine".format(engine))
		elif isinstance(db, list) and engine != "csv":
			raise ValueError("{0} does not support multiple database files".format(engine))

		self.user_settings["database"]["engine"] = engine

	def init_environment(self):

		for d in [
			self.environment_src,
			os.path.join(self.environment_src, "assets"),
			os.path.join(self.environment_src, "pages"),
			os.path.join(self.environment_src, "templates"),
			os.path.join(self.environment_dist)
		]:
			if not os.path.exists(d):
				os.mkdir(d)

		with open(os.path.join(self.environment_src, "settings.yaml"), "w") as settings_file:
			yaml.dump(self.settings, settings_file, default_flow_style=False)

		with open(os.path.join(self.environment_src, "user.yaml"), "w") as settings_file:
			yaml.dump(self.user_settings, settings_file, default_flow_style=False)

		with open(os.path.join(self.environment_src, "views.yaml"), "w") as views_file:
			pass

	@property
	def environment_src(self):
		return os.path.join(self.environment, "src")

	@property
	def environment_dist(self):
		return os.path.join(self.environment, "distribute")

	@property
	def routes(self):
		return self._routes()

	def _routes(self, views=None):

		routeList = []

		views = views or self.views

		for view in views:
			if view.get("subviews"):
				routeList += self._routes(views=view["subviews"])
			else:
				routeList.append(view["full_route"])

		return routeList

	def set_view_full_routes(self, views=None, route_prefix="/"):
		"""set full routes for each view"""

		views = views or self.views

		for view in views:
			# print(view["route"])
			if not view["route"]:
				view["full_route"] = ""
			else:
				# expand view to multiple subviews if required (i.e.,
				# "blog/posts/index.html" becomes "blogs", "posts",
				# "index.html")
				components = _path_splitall(view["route"])
				if components[0]:
					view["route"] = components[0]
					if not view.get("subviews"):
						originalSubviews = []
					else:
						originalSubviews = list(view["subviews"])

					view["subviews"] = []

					subviews = view["subviews"]
					for i, c in enumerate(components[1:]):
						newView = {
							"route": c,
							"subviews": []
						}
						subviews.append(newView)
						subviews = newView["subviews"]
					subviews.extend(originalSubviews)

				view["full_route"] = route_prefix + view["route"]

			if view.get("subviews"):
				self.set_view_full_routes(views=view["subviews"], route_prefix = view["full_route"] + "/")
			elif not view["route"]:
				raise ValueError("view route must not be blank unless view has subviews")

	def set_view_parameter(self, views, key, default_value, value=None):
		""" recursively set a parameter for a view and its subviews """

		if value == None:
			value = default_value

		for view in views:
			if view.get(key) == None:
				view[key] = copy.deepcopy(value)

			if view.get("subviews"):
				self.set_view_parameter(view["subviews"], key, default_value, value=view[key])

	def build(self, out=""):

		return self._build(out)

	def _build(self, out="", views=None):

		out = out or self.environment_dist
		if os.path.abspath(self.environment_src) in os.path.abspath(out):
			raise OSError("Cannot build site in source directory")

		if not os.path.exists(self.environment_src):
			raise OSError("Cannot find source directory")

		views = views or self.views

		if os.path.exists(out):
			if views == self.views:
				shutil.rmtree(out)
				os.mkdir(out)
		else:
			os.mkdir(out)

		md = markdown.Markdown(
			extensions = [MetaExtension()] + self.settings["pages"]["extensions"],
			extension_configs = self.settings["pages"]["extension_options"]
		)

		#copy assets (skip if this is not the top level of the recursive build)
		if views == self.views:
			try:
				assets_folder = os.path.join(self.environment_src, self.settings["environment"]["assets"])
				for f in os.listdir(assets_folder):
					if os.path.isdir(os.path.join(assets_folder, f)):
						shutil.copytree(os.path.join(assets_folder, f), os.path.join(out, f))
					else:
						shutil.copy(os.path.join(assets_folder, f), out)
			except OSError:
				print("Could not copy assets")

			#reset g
			self.g = {}

		tmp_fname  = os.path.join(self.environment_src, "templates", "_tmp.html")

		#create the html pages
		for view in views:

			#if there are subviews, we should build those instead
			if view.get("subviews"):
				new_out = os.path.join(out, view["route"])
				self._build(out=new_out, views=view["subviews"])
				continue

			#else, build the page for this view

			# create context dict
			context = dict(
				[(k, globals()["__builtins__"][k]) for k in self.settings["templates"]["builtins"]],
				full_route=view["full_route"],
				route=view["route"],
			)
			context.update(**view.get("context", {}))

			# query the database
			context["query"] = self.query_db(view.get("query"))

			#determine the markdown pages to use for this view

			page_fnames = view.get("pages")
			if page_fnames == None:
				page_fnames = ["".join(view["full_route"].lstrip("/").split(".")[:-1]) + ".md"]
			if page_fnames:
				page_fnames = [os.path.join(
					self.environment_src,
					self.settings["environment"]["pages"],
					fname
				) for fname in _collection(page_fnames)]
			else:
				page_fnames = []

			#load the context processor
			#syntax: "module.submodule:callable"
			context_processor_name = view.get("context_processor")
			if context_processor_name:
				try:
					# module_name, variable_name = context_processor_name.split(":")
					module, context_processor = _eval_module_and_object(context_processor_name)
				except ValueError:
					raise ValueError("incorrect syntax for 'context_processor'")

			else:
				context_processor = None

			with codecs.open(os.path.join(out, view["route"]), mode="w", encoding="utf-8") as out_file:
				try:
					blocks = {}
					tmp_template = "{{% extends '{0}' %}}".format(view["template"])

					for page_fname in page_fnames:
						# with open(page_fname, "r") as page_file:
						with codecs.open(page_fname, mode="r", encoding="utf-8") as page_file:
							html = md.convert(six.text_type(page_file.read()))
							html = html.replace("%", "&#37;").replace("{", "&#123;").replace("}", "&#125;")
							meta = {}
							special = {}

							for k, v in md.Meta.items():
								# double-underscore vars are special vars used by gansa
								if k == "__block__":
									d = special
								else:
									d = meta

								# v will always be a list, which is probably not what users want
								# if only one item is specified
								if len(v) == 1:
									d[k] = v[0]
								else:
									d[k] = v

							context.update(meta)

							block_name = special.get("__block__", self.settings["templates"]["default_block"])
							blocks[block_name] = html

							tmp_template += six.text_type("{{% block {0}%}}{1}{{% endblock %}}").format(block_name, html)

					with codecs.open(tmp_fname, mode="w", encoding="utf-8") as tmp:
						tmp.write(tmp_template)

					template = self.templates.get_template("_tmp.html")
				# if no markdown page was found, just write context variables to the template
				except OSError:
					template = self.templates.get_template(view["template"])

				if context_processor:
					new_context = context_processor(context, dict(view), self)
					if new_context != None:
						context = new_context

				try:
					stream = template.render(**context)
				except TypeError:
					raise TypeError("context processor must return dict or other mapping")

				out_file.write(stream)
		if views == self.views:
			try:
				os.remove(tmp_fname)
			except OSError:
				pass

		if views == self.views and self.settings["callbacks"].get("postrender"):
			try:
				_, callback = _eval_module_and_object(self.settings["callbacks"]["postrender"])
			except ValueError:
				raise ValueError("incorrect syntax for 'postrender'")
			callback(self, {"views":views, "out":out})

	def query_db(self, query=None):

		if not self.db:
			return

		method = {
			"yaml": self._query_yaml,
			"sqlite": self._query_sqlite,
			"postgresql": self._query_postgresql,
			"mysql": self._query_mysql,
			"csv": self._query_csv,
			"mongodb": self._query_mongodb
		}[self.user_settings["database"]["engine"]]

		r = method(query)
		return r

	def _query_yaml(self, query=None):

		if not query:
			return self.db

		condition = eval("lambda db: " + query, {})

		return condition(self.db)

	def _query_sqlite(self, query=None):
		return self._query_sql(query)

	def _query_postgresql(self, query=None):
		return self._query_sql(query)

	def _query_mysql(self, query=None):
		return self._query_sql(query)

	def _query_mongodb(self, query=None):

		if not query:
			return None

		if not query.get("model"):
			raise KeyError("query must specify database model")

		_, model = _eval_module_and_object(query["model"])

		q = model.objects

		if query.get("filter"):
			q = q.filter(**query["filter"])

		if query.get("order"):
			order = _collection(query["order"])
			q = q.order_by(*order)

		return q

	def _query_sql(self, query=None):

		if not query:
			return self.db
		elif isinstance(query, six.string_types):
			return [row for row in self.db_engine.execute(query)]

		if not query.get("models"):
			raise KeyError("query must specify database models")

		models_modules = {"sqlalchemy": sqlalchemy}
		models = []
		for s in  _collection(query["models"]):
			try:
				_, model = _eval_module_and_object(s)
				models.append(model)

				module_name = s.split(":")[0].split(".")
				for i, sub in enumerate(module_name):
					full_name = ".".join(module_name[:i+1])
					models_modules[full_name] = importlib.import_module(full_name)
			except ValueError:
				raise ValueError("incorrect syntax for 'models'")

		q = self.db.query(*models)

		if query.get("join"):
			joins = _collection(query["join"])
			args = []

			for j in joins:
				args.append(eval("lambda: " + j, models_modules)())

			q = q.join(*args)

		if query.get("filter"):
			filters = _collection(query["filter"])

			for fil in filters:
				q = q.filter(eval("lambda: " + fil, models_modules)())

		if query.get("order"):
			order = _collection(query["order"])

			for o in order:
				f = eval("lambda: " + o, models_modules)
				q = q.order_by(f())

		return q.all()

	def _query_csv(self, query=None):

		if not query:
			return self.db

		table = self.db.get(query.get("table"))
		if not table:
			raise KeyError("table {0} not found in database".format(repr(query.get("table"))))

		copy = list(table)

		if query.get("filter"):
			# if not isinstance(query["filter"], list):
			# 	query["filter"] = [query["filter"]]
			query["filter"] = _collection(query["filter"])

			conditions = [eval("lambda row: " + l, {}) for l in query["filter"]]

			def filter_key(item):
				for condition in conditions:
					if not condition(item):
						return False

				return True

			copy = filter(filter_key, copy)

		if query.get("order"):
			# if not isinstance(query["order"], list):
			# 	query["order"] = [query["order"]]

			order = []
			for k in _collection(query["order"]):
				#normalize the key into a tuple, with "ascending" or "descending" as the second element

				if isinstance(k, six.string_types):
					_o = k.split(" ")

					if len(_o) > 1 and _o[-1] in {"ascending", "descending"}:
						v = (" ".join(_o[:-1]), o[-1])
					else:
						try:
							v = (_tonumber(_o[0]), "ascending")
						except:
							v = (_o[0], "ascending")

					order.append(v)
				else:
					order.append((k, "ascending"))

			for k in reversed(order):
				copy.sort(key = (lambda item: item[k[0]]), reverse=(k[1]=="descending"))
				# print(copy)

		return copy
