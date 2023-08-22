# Scripts

## Dot.py
For visualizing `codeinfo.json` using `dot` and generting `svg` files.

You have to install `graphviz` by the following for Mac (or google it for your platform)

```
brew install graphviz
```

Then run
```
python ./codebase_analyzer/scripts/dot.py \
    --input-path ./shared_cache/Auto-GPT/codeinfo.json \
    --output-path ./graph \
    --show-node package \  # package node will be shown
    --show-node module \  # module node will be shown
    --show-edge children  # children edge will be shown
```
If no `--shown-node` or `--shown-edge` are assigned, all nodes and edges will be shown.
