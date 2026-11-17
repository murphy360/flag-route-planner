# The image the tests run in (CI: test-docker). Run the planner with it too: see the README.
# The checkout is mounted at /src when the tests run, so the editable install below finds your code there.
FROM python:3.15-slim

WORKDIR /src
COPY pyproject.toml ./
COPY src ./src
# Installs the package (with openpyxl) and pytest.
RUN pip install --no-cache-dir -e ".[test]"
COPY tests ./tests

# Running the image with no arguments runs the tests; CI runs them with its own command.
CMD ["pytest", "-q"]
