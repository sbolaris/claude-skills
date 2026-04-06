# Skill: R-to-Python Migration in Nextflow Pipelines

**When to use:** Replacing R scripts with Python equivalents in a Nextflow pipeline while eliminating the R container dependency.

---

## Migration checklist

1. **Audit R usage** — find all `.R` files, `Rscript` calls in Nextflow modules, R containers, and config references
2. **Translate the script** — map R functions to pandas equivalents:
   | R | Python (pandas) |
   |---|-----------------|
   | `read.table(f, sep="\t", header=T)` | `pd.read_csv(f, sep='\t')` |
   | `merge(df1, df2, by="col")` | `df1.merge(df2, on='col')` |
   | `write.table(df, f, sep=",", row.names=F)` | `df.to_csv(f, index=False)` |
   | `df[df$Col > val,]` | `df[df['Col'] > val]` |
   | `commandArgs(trailingOnly=T)` | `sys.argv[1:]` |
   | `list.files(dir, recursive=T, pattern="foo")` | `pathlib.Path(dir).rglob("*foo*")` |
   | `dirname(path)` | `pathlib.Path(path).parent` |
   | `colnames(df)[1] = "Name"` | `df.columns = ['Name'] + list(df.columns[1:])` |

3. **Simplify argument passing** — R scripts often use directory-walking (`list.files`) to find inputs. Python replacements should accept explicit file paths as arguments instead.

4. **Update the Nextflow module** — change `Rscript` to `python3`, update argument list, remove scratch dir setup that was needed for R's directory-walking pattern.

5. **Update container assignment** — move the process from the R container to the Python container in `nextflow.config` `withName` selectors. Verify the Python container already has `pandas`.

6. **Add script to Python Dockerfile** — add a `COPY src/new_script.py src/` line.

7. **Delete R artifacts:**
   - The `.R` script
   - `containers/r/Dockerfile` and `containers/r/env.yaml`
   - Remove `r` from `CONTAINERS` array in `build.sh`

8. **Update docs** — CLAUDE.md, technical docs, container tables, file maps.

9. **Write tests** — create a pytest test file that validates the Python script produces identical output to what the R script produced.

## Key gotcha

R's `write.table` with `sep=","` and `row.names=F` produces CSV without an index column. pandas `to_csv(index=False)` matches this. But R's `read.table` with `header=T` auto-names columns `X1, X2...` when headers are missing — pandas raises an error instead. Make sure column name handling is explicit.

## R's `merge` vs pandas `merge`

R's `merge(x, y, by="col", all=T)` is an outer join. pandas equivalent: `x.merge(y, on='col', how='outer')`. Without `all=T`, R defaults to inner join — same as pandas default.
