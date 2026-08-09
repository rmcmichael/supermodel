# SuperModel Design Notes

Easy Pyhon class oriented, model-first access to SQLite

## Database

## Model

### Differences in a approach from the original implementation

- Id's are now UUIDv7
  - Previously, models were identified by a auto-incrementing database column
  - Now, models are identified by a string populated by a UUIDv7 value
  - The id attribute is set when the model is instantiated
  - Id's are now immutable by the caller
  - The primary key for the model's backing table will be a TEXT column named ID

- Type Inference
  - Previously, the type of the table column was determined by the value that an attribute was initialize with.
  - Now they type of the table column will be determined by the type hint associated with the class attribute
  - Example: `name : str = ""` will result in a TEXT column in the backing table

- Null Columns
  - Previously, null columns were not allowed. Every column had to be populated with a value
  - This was largely because type inference required an initial column value
  - Now, if the type hint for an attribute is declared optional, the column in the backing table is allowed to contain a null
  - Example: `name : optional(str) = None` will create a TEXT column that allows nulls

- Schema Updates
  - Previously, the calling application had to call the check_schema() method for every model
  - Now, models are registered with the Database singleton class
  - When the first connection is lazily initiated, it will first create the table if it doesn't exist, with the ID primary key. Then it will iterate through the registered models and add columns as necessary
  - The check_schema() method will now be private

- Table and Column Names
  - By default, table names will be derived from the model class name as all caps and snake case
  - By dolumn names will be derived from the attribute name as all caps and snake case
  - The user can now specify the table name with the `table_name` attribute (via a getter and setter)
  - The user can now specify a columnand `column_name(attribute_name, column_name) method`

### Model Attribute to Table Column Mapping

| Python Type             | Column DDL                                              |
| ----------------------- | ------------------------------------------------------- |
| int                     | INTEGER NOT NULL DEFAULT 0                              |
| optional(int)           | INTEGER DEFAULT NULL                                    |
| float                   | REAL NOT NULL DEFAULT 0.0                               |
| optional(float)         | REAL DEFAULT NULL                                       |
| datetime.date           | TEXT NOT NULL DEFAULT "0001-01-01"                      |
| optional(datetime.date) | TEXT DEFAULT NULL                                       |
| datetime.time           | TEXT NOT NULL DEFAULT "00:00:00.000000"                 |
| optional(datetime.time) | TEXT DEFAULT NULL                                       |
| datetime                | TEXT NOT NULL DEFAULT "0001-01-01T00:00:00.000000+00:00 |
| optional(datetime)      | TEXT DEFAULT NULL                                       |
| bool                    | INTEGER NOT NULL DEFAULT 0                              |
| optional(bool)          | INTEGER DEFAULT NULL                                    |
| str                     | TEXT NOT NULL DEFAULT ""                                |
| optional(str)           | TEXT DEFAULT NULL                                       |

### Implementation Notes on Types

- Every model has a private \_columns map that will contain one item per attribute
- The key will be the attribute name
- Each item will be an instance of a subclass of Column by type
- The Column subclasses are IntColumn, FloatColumn, DateColumn, TimeColumn, DateTimeColumn, BoolColumn, and TextColumn
- Model will delegate the DDL and value translation activies into those classes
- Non-optional date attributes should be set to a specific value by the user. The column default of "0001-01-01" should not be used in practice
- Non-optional time attributes should be set to a specific value by the user. The column default of "00:00:00" should not be used
- time attributes are naive and do not specify a timezone
- datetime attributes are not naive, and are timezone aware. If a naive datetime is passed to the setter, then it will be coerced to UTC
