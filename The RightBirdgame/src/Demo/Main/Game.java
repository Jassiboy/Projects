package Demo.Main;

import javax.swing.*;

/**
 * Created by jassiboy on 2/26/2017.
 */
public class Game {
    public static void main(String[] args) {
        JFrame frame = new JFrame();
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.setResizable(false);
        GamePanel panel = new GamePanel();
        frame.add(panel);
        frame.pack();
        frame.setVisible(true);
    }
}
