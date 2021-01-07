const path = require("path");
const CopyWebpackPlugin = require("copy-webpack-plugin")

module.exports = {
  entry: ["babel-polyfill", __dirname + "/src/js/index.jsx"],
  output: {
    path: path.resolve(__dirname, "../imbi/static/"),
    publicPath: "/static/",
    filename: "imbi.js",
  },
  performance: {hints: false},
  resolve: {
    extensions: [".js", ".jsx"]
  },
  module: {
    rules: [
      {
        test: /\.(js|jsx)$/,
        exclude: /node_modules/,
        loader: "babel-loader"
      },
      {
        test: /\.(woff(2)?|ttf|eot|svg)(\?v=\d+\.\d+\.\d+)?$/,
        loader: "file-loader",
        options: {
          name: "[name].[ext]",
          outputPath: "fonts/"
        }
      },
      {
        test: /\.css$/i,
        use: ["style-loader", "css-loader", "resolve-url-loader", "postcss-loader"]
      }
    ]
  },
  plugins: [
    new CopyWebpackPlugin(
      {
        patterns: [
          {
            from: "node_modules/redoc/bundles/redoc.standalone.js",
            to: path.resolve(__dirname, "../imbi/static/"),
            flatten: true
          }
        ]
      }, {})
  ],
  watchOptions: {
    aggregateTimeout: 1000,
    ignored: "node_modules/**",
    poll: 1000
  }
};
