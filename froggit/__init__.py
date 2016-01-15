#!/usr/bin/env python

from __future__ import print_function
import sys, os, collections, shutil, csv, functools, copy, importlib
import jinja2, markdown, yaml, sqlalchemy, sqlalchemy.orm, mongoengine
from . import six
from markdown.extensions.meta import MetaExtension

TMP_TEMPLATE = """
{{% extends '{0}' %}}
{{% block {1} %}}
{2}
{{% endblock %}}
"""

#TODO: add mongodb, couchdb
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
			"extensions": []
		},
		"templates": {
			"default_block": "content"
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

			store_csv_as = self.user_settings["database"].get("store_csv_as", "array")
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

					if self.user_settings["database"].get("convert_numbers", True):
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
		self.set_view_templates()
		self.set_view_contexts()

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
			os.path.join(self.environment, "distribute")
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

	def set_view_full_routes(self, views=None, route_prefix="/"):
		"""set full routes for each view"""

		views = views or self.views

		for view in views:
			view["full_route"] = route_prefix + view["route"]
			if view.get("subviews"):
				self.set_view_full_routes(views=view["subviews"], route_prefix = view["full_route"] + "/")
			elif not view["route"]:
				raise ValueError("view route must not be blank unless view has subviews")

	def set_view_templates(self, views=None, template=""):
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
				self.set_view_templates(views=view["subviews"], template=view["template"])

	def set_view_contexts(self, views=None, context=None):
		"""set context tables for each view"""

		views = views or self.views
		context = context or {}

		for view in views:
			if not view.get("context"):
				view["context"] = copy.deepcopy(context)

			if view.get("subviews"):
				self.set_view_contexts(views=view["subviews"], context=view["context"])

	def build(self, out="", views=None):

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

		md = markdown.Markdown(extensions = [MetaExtension()] + self.settings["pages"]["extensions"])

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

			# create context dict
			context = dict(route=view["full_route"], **view.get("context", {}))
			# query the database

			context["query"] = self.query_db(view.get("query"))

			#determine the markdown pages to use for this view

			page_fnames = view.get("pages", ["".join(view["full_route"].lstrip("/").split(".")[:-1]) + ".md"])
			page_fnames = _collection(page_fnames)

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
					# module_name, variable_name = context_processor_name.split(":")
					module, context_processor = _eval_module_and_object(context_processor_name)
				except ValueError:
					raise ValueError("incorrect syntax for 'context_processor'")

				# module = imp.load_source("context_processor", os.path.join(self.environment_src, module_name))
				# module = importlib.import_module(module_name)
				# variable_name_list = variable_name.split(".")
				# o = module

				# for v in variable_name_list:
				# 	o = getattr(o, v)

				# context_processor = o
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

							block_name = special.get("__block__", self.settings["templates"]["default_block"])
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

		if not self.db:
			return

		method = {
			"yaml": self.query_yaml,
			"sqlite": self.query_sqlite,
			"postgresql": self.query_postgresql,
			"mysql": self.query_mysql,
			"csv": self.query_csv,
			"mongodb": self.query_mongodb
		}[self.user_settings["database"]["engine"]]

		r = method(query)
		return r

	def query_yaml(self, query=None):

		if not query:
			return self.db

		condition = eval("lambda db: " + query, {})

		return condition(self.db)
	
	def query_sqlite(self, query=None):
		return self.query_sql(query)
	
	def query_postgresql(self, query=None):
		return self.query_sql(query)
	
	def query_mysql(self, query=None):
		return self.query_sql(query)

	def query_mongodb(self, query=None):

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

	def query_sql(self, query=None):

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
			# if not isinstance(query["order"], list):
			# 	query["order"] = [query["order"]]

			order = [k.split(" ") for k in _collection(query["order"])]

			for i, key in enumerate(order):
				if key[-1] in {"ascending", "descending"}:
					order[i] = (" ".join(key[:-1]), key[-1])
				else:
					order[i] = (" ".join(key), "ascending")

			for k in reversed(order):
				copy.sort(key = (lambda item: item[k[0]]), reverse=(k[1]=="descending"))
				# print(copy)

		return copy
