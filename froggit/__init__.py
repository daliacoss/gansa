#!/usr/bin/env python

from __future__ import print_function
import os, collections, shutil, csv, functools, imp
# from importlib import import_module
import jinja2, markdown, yaml, sqlalchemy
from . import six
from markdown.extensions.meta import MetaExtension

TMP_TEMPLATE = """
{{% extends '{0}' %}}
{{% block {1} %}}
{2}
{{% endblock %}}
"""

#TODO: add mongodb, couchdb
SUPPORTED_DB_ENGINES = {"yaml", "sqlite", "postgresql", "mysql", "csv"}

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

class Site(object):

	default_settings = {
		"database": {},
		"environment": {
			"views": "views.yaml",
			"pages": "pages",
			"templates": "templates",
			"assets": "assets",
			"database": "db.yaml"
		},
		"default_block": "content"
	}

	def __init__(self, environment, load=True):

		self.environment = os.path.abspath(environment)
		self.settings = dict(self.default_settings)
		self.views = []

		if not load or not os.path.exists(self.environment_src):
			return

		try:
			self.load_environment()
		except IOError, OSError:
			pass

	def load_environment(self):

		self.load_settings()
		self.load_templates()
		self.load_views()
		self.load_db()

	def load_db(self):

		db_engine = self.settings["database"].get("engine")
		if not db_engine:
			return

		if db_engine == "yaml":
			with open(os.path.join(self.environment_src, self.settings["environment"]["database"])) as stream:
				self.db = yaml.load(stream) or {}
		elif db_engine == "csv":
			db_fnames = self.settings["environment"]["database"]
			if not isinstance(db_fnames, list):
				db_fnames = [db_fnames]

			store_csv_as = self.settings["database"].get("store_csv_as", "array")
			self.db = {}

			for fname in db_fnames:
				with open(os.path.join(self.environment_src, fname)) as stream:
					table_name = ".".join(fname.split(".")[:-1])
					if store_csv_as == "dict":
						self.db[table_name] = [row for row in csv.DictReader(stream)]
					elif store_csv_as == "array":
						self.db[table_name] = [row for row in csv.reader(stream)]
					else:
						raise ValueError("{0} is not a recognized csv storage format".format(store_csv_as))

					if self.settings["database"].get("convert_numbers", True):
						for row in self.db[table_name]:
							if store_csv_as == "dict":
								for k, v in row.items():
									try:
										row[k] = _tonumber(v)
									except:
										pass
							if store_csv_as == "array":
								for i, v in enumerate(row):
									try:
										row[i] = _tonumber(v)
									except:
										pass

	def load_templates(self):

		template_loader = jinja2.FileSystemLoader(os.path.join(self.environment_src, self.settings["environment"]["templates"]))
		self.templates = jinja2.Environment(cache_size=0, loader=template_loader)

	def load_views(self):

		with open(os.path.join(self.environment_src, self.settings["environment"]["views"])) as vstream:
			self.views = yaml.load(vstream) or []
		self.set_full_routes()
		self.set_templates()

	def load_settings(self, merge=True):
		"""
		load settings from this project's settings.yaml file

		parameters:
			merge=True: attempt to merge settings with already loaded settings
		"""

		with open(os.path.join(self.environment_src, "settings.yaml")) as settings_file:
			settings = yaml.load(settings_file)
			_deep_update(self.settings, settings)

		db = self.settings["environment"]["database"]

		if not db:
			return

		if isinstance(db, list):
			fname = db[0]
		else:
			fname = db

		# attempt to infer db engine from file name, if one is not specified
		engine = self.settings["database"].get("engine") or {
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

		self.settings["database"]["engine"] = engine

	def init_environment(self):

		for d in [
			self.environment_src,
			os.path.join(self.environment_src, "assets"),
			os.path.join(self.environment_src, "pages"),
			os.path.join(self.environment_src, "templates"),
			os.path.join(self.environment, "distribute")
		]:
			if not os.path.exists(d):
				os.mkdir(d)

		with open(os.path.join(self.environment_src, "settings.yaml"), "w") as settings_file:
			yaml.dump(self.settings, settings_file, default_flow_style=False)

		with open(os.path.join(self.environment_src, "views.yaml"), "w") as views_file:
			pass

		db_filename = self.settings["environment"]["database"]
		with open(os.path.join(self.environment_src, db_filename), "w") as views_file:
			pass

	@property
	def environment_src(self):
		return os.path.join(self.environment, "src")

	@property
	def environment_dist(self):
		return os.path.join(self.environment, "dist")

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

	def set_full_routes(self, views=None, route_prefix="/"):
		"""set full routes for each view"""

		views = views or self.views

		for view in views:
			view["full_route"] = route_prefix + view["route"]
			if view.get("subviews"):
				self.set_full_routes(views=view["subviews"], route_prefix = view["full_route"] + "/")
			elif not view["route"]:
				raise ValueError("view route must not be blank unless view has subviews")

	def set_templates(self, views=None, template=""):
		"""
		explicitly set templates for each view.

		if a view template is not explicitly defined, refer to the nearest
		ancestor with an explicitly defined template.
		"""

		views = views or self.views

		for view in views:
			if not view.get("template"):
				view["template"] = template

			if view.get("subviews"):
				self.set_templates(views=view["subviews"], template=view["template"])

	def build(self, out="", views=None):

		out = out or self.environment_dist
		if os.path.abspath(self.environment_src) in os.path.abspath(out):
			raise OSError("Cannot build site in source directory")

		views = views or self.views

		if os.path.exists(out):
			if views == self.views:
				shutil.rmtree(out)
				os.mkdir(out)
		else:
			os.mkdir(out)

		md = markdown.Markdown(extensions=[MetaExtension()])

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
		tmp_fname  = os.path.join(self.environment_src, "templates", "_tmp.html")

		#create the html pages
		for view in views:

			#if there are subviews, we should build those instead
			if view.get("subviews"):
				new_out = os.path.join(out, view["route"])
				self.build(out=new_out, views=view["subviews"])
				continue

			#else, build the page for this view

			context = dict(route=view["full_route"], **view.get("context", {}))
			context["query"] = self.query_db(view.get("query"))

			#determine the markdown pages to use for this view

			page_fnames = view.get("pages", ["".join(view["full_route"].lstrip("/").split(".")[:-1]) + ".md"])

			if not isinstance(page_fnames, collections.Iterable) or isinstance(page_fnames, six.string_types):
				page_fnames = [page_fnames]

			page_fnames = [os.path.join(
				self.environment_src,
				self.settings["environment"]["pages"],
				fname
			) for fname in page_fnames]

			#load the context processor
			#syntax: "module.submodule:callable"
			context_processor_name = view.get("context_processor")
			if context_processor_name:
				try:
					module_name, variable_name = context_processor_name.split(":")
				except ValueError:
					raise ValueError("incorrect syntax for context_processor value")

				# module = import_module(module_name)
				module = imp.load_source("context_processor", os.path.join(self.environment_src, module_name))
				variable_name_list = variable_name.split(".")
				o = module

				for v in variable_name_list:
					o = getattr(o, v)

				context_processor = o
			else:
				context_processor = None

			with open(os.path.join(out, view["route"]), "w") as out_file:
				try:
					blocks = {}
					tmp_template = "{{% extends '{0}' %}}".format(view["template"])

					for page_fname in page_fnames:
						with open(page_fname, "r") as page_file:
							html = md.convert(page_file.read())
							meta = {}
							special = {}

							for k, v in md.Meta.items():
								# double-underscore vars are special vars used by froggit
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

							block_name = special.get("__block__", self.settings["default_block"])
							blocks[block_name] = html
							tmp_template += "{{% block {0}%}}{1}{{% endblock %}}".format(block_name, html)

					if context_processor:
						context = context_processor(context, dict(view))

					with open(tmp_fname, "w") as tmp:
						tmp.write(tmp_template)

					template = self.templates.get_template("_tmp.html")
					out_file.write(template.render(**context))
				# if no markdown page was found, just write context variables to the template
				except OSError:
					template = self.templates.get_template(view["template"])
					out_file.write(template.render(**context).encode('utf8'))

		if views == self.views:
			try:
				os.remove(tmp_fname)
			except OSError:
				pass

	def query_db(self, query=None):

		method = {
			"yaml": self.query_yaml,
			"sqlite": self.query_sqlite,
			"postgresql": self.query_postgresql,
			"mysql": self.query_mysql,
			"csv": self.query_csv
		}[self.settings["database"]["engine"]]

		return method(query)

	def query_yaml(self, query=None):

		if not query:
			return self.db

		condition = eval("lambda db: " + query, {})

		return condition(self.db)
	
	def query_sqlite(self, query=None):
		pass
	
	def query_postgresql(self, query=None):
		pass
	
	def query_mysql(self, query=None):
		pass
	
	def query_csv(self, query=None):
		

		if not query:
			return self.db

		table = self.db.get(query.get("table"))
		if not table:
			raise KeyError("table {0} not found in database".format(repr(query.get("table"))))

		copy = list(table)

		if query.get("filter"):
			if not isinstance(query["filter"], list):
				query["filter"] = [query["filter"]]

			conditions = [eval("lambda row: " + l, {}) for l in query["filter"]]

			def filter_key(item):
				for condition in conditions:
					if not condition(item):
						return False

				return True

			copy = filter(filter_key, copy)

		if query.get("order"):
			if not isinstance(query["order"], list):
				query["order"] = [query["order"]]

			order = [k.split(" ") for k in query["order"]]

			for i, key in enumerate(order):
				if key[-1] in {"ascending", "descending"}:
					order[i] = (" ".join(key[:-1]), key[-1])
				else:
					order[i] = (" ".join(key), "ascending")

			for k in reversed(order):
				copy.sort(key = (lambda item: item[k[0]]), reverse=(k[1]=="descending"))
				# print(copy)

		return copy
