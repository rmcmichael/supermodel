from db.database import Database
import datetime
import dateparser
import re
import json


# Column Type | Python Type       | Mapping
# ID          | int               | INTEGER PRIMARY KEY AUTOINCREMENT
# TEXT        | str               |
# INTEGER     | int               |
# REAL        | float             |
# DATE        | datetime.date     | TEXT column 'YYYY-MM-DD'
# TIME        | datetime.time     | TEXT column 'HH:MM:SS'
# DATETIME    | datetime.datetime | TEXT column 'YYYY-MM-DD HH:MM:SS.999999'
# BOOL        | bool              | INTEGER column, 1 = True, 0 = False
class ModelException(Exception):
    def __init__(self, message=""):
        super().__init__(message)


class Model:
    # Class variables to be overriden by child classes
    _is_schema_checked = False
    _db = Database()

    def __init__(self):
        self.id = None

    def save(self, success=None):
        self.check_schema()
        if self.id is None:
            self.insert_row()
        else:
            self.update_row()

        if success is not None:
            success(self)
        return self

    def get(self, id: int):
        self.check_schema()
        if not self._db.table_exists(self.get_table_name()):
            raise ModelException(
                "Id {} does not exist in Model {}".format(id, self.get_table_name())
            )

        stmt = "SELECT * FROM {} WHERE id=?".format(self.get_table_name())
        result = self._db.execute(stmt, [id])
        row = result.fetchone()
        if row is None:
            raise ModelException(
                "Id {} does not exist in Model {}".format(id, self.get_table_name())
            )
        self.set_from_row(row)
        return self

    def getone(self):
        self.check_schema()
        if self.count() > 1:
            raise ModelException(
                "Cannot call Model.getone on a table with more than one row"
            )

        if self._db.table_exists(self.get_table_name()):
            stmt = "SELECT * FROM {}".format(self.get_table_name())
            result = self._db.execute(stmt)
            row = result.fetchone()
            self.set_from_row(row)
        return self

    def remove(self, success=None):
        self.check_schema()
        if self.id is not None:
            stmt = "DELETE FROM {} WHERE id=?".format(self.get_table_name())
            self._db.execute(stmt, [self.id])
        #            self.id = None

        if success is not None:
            success(self)
        return self

    @classmethod
    def select(
        cls,
        orderby: [] = None,
        groupby: [] = None,
        where: [] = None,
    ):

        models = []

        if not cls._db.table_exists(cls.get_table_name()):
            return models

        stmt = "SELECT * FROM {}".format(cls.get_table_name())

        if orderby is not None:
            stmt += " ORDER BY "
            order_str = ", ".join(orderby)
            order_str = order_str.replace("-", " DESC")
            order_str = order_str.replace("+", " ASC")
            stmt += order_str

        for row in cls._db.execute(stmt):
            model = cls().set_from_row(row)
            if where is not None and not where(model):
                continue
            models.append(cls().set_from_row(row))

        # Group the results by the field name in the groupby clause
        if groupby is not None:
            grouped = []
            last_item = None
            last_value = None
            for model in models:
                value = groupby(model)
                if value != last_value:
                    last_item = [value, [model]]
                    last_value = value
                    grouped.append(last_item)
                else:
                    last_item[1].append(model)
            models = grouped

        # Return the results
        return models

    @classmethod
    def count(cls):
        if cls._db.table_exists(cls.get_table_name()):
            stmt = "SELECT COUNT(*) AS count FROM {}".format(cls.get_table_name())
            count = cls._db.execute(stmt).fetchone()["count"]
            return count
        else:
            return 0

    def set_from_row(self, row):
        self.check_schema()
        for attr in self.attributes:
            v = row[attr]
            if type(getattr(self, attr)) is datetime.date:
                setattr(self, attr, datetime.datetime.strptime(v, "%Y-%m-%d").date())
            elif type(getattr(self, attr)) is datetime.time:
                setattr(self, attr, datetime.datetime.strptime(v, "%H:%M:%S").time())
            elif type(getattr(self, attr)) is bool:
                setattr(self, attr, True if v == 1 else False)
            else:
                setattr(self, attr, v)
        return self

    def set(self, vals={}):
        for attr in self.attributes:
            if attr in vals:
                v = vals[attr]
                if type(getattr(self, attr)) is datetime.date:
                    if type(v) is str:
                        setattr(self, attr, dateparser.parse(v).date())
                elif type(getattr(self, attr)) is datetime.time:
                    if type(v) is str:
                        setattr(self, attr, dateparser.parse(v).time())
                elif type(getattr(self, attr)) is bool:
                    setattr(self, attr, True if v == 1 else False)
                else:
                    setattr(self, attr, v)
        return self

    def insert_row(self):
        stmt = """INSERT INTO {} ({}) VALUES ({})"""
        attrs = self.attributes
        attrs.remove("id")
        columns = ", ".join(attrs)
        placeholders = ", ".join([":" + attr for attr in attrs])
        result = self._db.execute(
            stmt.format(self.get_table_name(), columns, placeholders), self.sql_values
        )
        self.id = result.lastrowid

    def update_row(self):
        stmt = """UPDATE {} SET {} WHERE ID = :id"""
        attrs = self.attributes
        columns = ", ".join([attr + "=:" + attr for attr in attrs])
        self._db.execute(stmt.format(self.get_table_name(), columns), self.sql_values)

    def check_schema(self):
        if not self.__class__._is_schema_checked:
            self.__class__._is_schema_checked = True

            # Create the table if necessary
            tableCreated = False
            if not self._db.table_exists(self.get_table_name()):
                self.create_table()
                tableCreated = True

            for attr in self.attributes:
                if not self._db.column_exists(self.get_table_name(), attr):
                    self.create_column(attr)

            if tableCreated:
                self.on_table_created()

    def on_table_created(self):
        """Override this method in child classes to perform any actions after the table is created"""
        pass

    def create_table(self):
        stmt = "CREATE TABLE {} (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        self._db.execute(stmt.format(self.get_table_name()))

    def create_column(self, attr: str):
        v = getattr(self, attr, None)
        if type(v) is int:
            stmt = "ALTER TABLE {} ADD COLUMN {} INTEGER NOT NULL DEFAULT 0"
        elif type(v) is float:
            stmt = "ALTER TABLE {} ADD COLUMN {} REAL NOT NULL DEFAULT 0.0"
        elif type(v) is datetime.date:
            stmt = 'ALTER TABLE {} ADD COLUMN {} TEXT NOT NULL DEFAULT "0001-01-01"'
        elif type(v) is datetime.time:
            stmt = 'ALTER TABLE {} ADD COLUMN {} TEXT NOT NULL DEFAULT "00:01:01"'
        elif type(v) is bool:
            stmt = "ALTER TABLE {} ADD COLUMN {} INTEGER NOT NULL DEFAULT 0"
        else:
            stmt = 'ALTER TABLE {} ADD COLUMN {} TEXT NOT NULL DEFAULT ""'
        self._db.execute(stmt.format(self.get_table_name(), attr))
        return

    @property
    def attributes(self):
        """Return an array of model attribute names"""
        names = []
        for attr in dir(self):
            # Ignore private instance variables (_foo)
            # Ignore system instance variables (__foo__)
            if attr.startswith("_"):
                continue

            # Ignore property decorators
            if isinstance(getattr(type(self), attr, None), property):
                continue

            # Ignore functions
            if callable(getattr(self, attr)):
                continue

            names.append(attr)

        return names

    @property
    def dict(self):
        """Return a dictionary model attributes and values"""
        d = {k: getattr(self, k) for k in self.attributes}
        return d

    @property
    def sql_values(self):
        values = {}
        for attr in self.attributes:
            v = getattr(self, attr, None)
            if type(v) is datetime.date:
                values[attr] = v.strftime("%Y-%m-%d")
            elif type(v) is datetime.time:
                values[attr] = v.strftime("%H:%M:%S")
            elif type(v) is bool:
                values[attr] = 1 if v else 0
            else:
                values[attr] = v
        return values

    @property
    def json_values(self):
        values = {}
        for attr in self.attributes:
            v = getattr(self, attr, None)
            if type(v) is datetime.date:
                values[attr] = v.strftime("%Y-%m-%d")
            elif type(v) is datetime.time:
                values[attr] = v.strftime("%H:%M:%S")
            # elif type(v) is bool:
            # values[attr] = 1 if v else 0
            else:
                values[attr] = v
        return values

    @staticmethod
    def snake_case(camel_case_name):
        """Convert a camel case string to snake case"""
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", camel_case_name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    @classmethod
    def get_table_name(cls):
        return cls.snake_case(cls.__name__)

    @classmethod
    def load(cls, records=None, json_file=None):
        "Load and save multiple records from a list of dicts"
        if records is not None:
            for record in records:
                cls().set(record).save()

        if json_file is not None:
            recs = []
            with open(json_file) as file:
                recs = json.load(file)
            for rec in recs:
                cls().set(rec).save()
